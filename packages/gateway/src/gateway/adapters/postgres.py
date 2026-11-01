"""Adapter `postgres` cho port `KeyStore`.

L1 (dict TTL trong process: 10s, negative cache 5s) + L3 (Postgres, truy vấn tham số hoá).
Chưa có L2 Redis và thu hồi qua pub/sub: một key bị thu hồi có hiệu lực trong tối đa 10s (TTL L1)
ở các instance khác; instance thực hiện thu hồi thì ngay lập tức.
Tài liệu: docs/design/01-gateway.md §3.2.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import asyncpg
from acme_common.ports import Clock

from ..ports.errors import KeyAlreadyExists, KeyNotFound
from ..ports.key_store import KeyStore
from ..ports.types import KeyRecord, NewKey

L1_TTL_S = 10.0
L1_NEG_TTL_S = 5.0
L1_MAXSIZE = 10_000

KEY_SQL = """
SELECT k.id::text AS key_id, k.prefix, k.secret_hmac, k.name, k.department AS dept, k.allowed_models,
       k.rpm_limit AS rpm, k.tpm_limit AS tpm, k.max_concurrency,
       k.trust_end_user_token, k.expose_debug, k.status, k.expires_at
FROM api_keys k
WHERE k.prefix = $1
"""

INSERT_SQL = """
INSERT INTO api_keys (prefix, secret_hmac, name, owner_type, owner_ref, department, allowed_models,
                      rpm_limit, tpm_limit, max_concurrency,
                      trust_end_user_token, expose_debug, created_by, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
"""

REVOKE_SQL = """
UPDATE api_keys SET status = 'revoked', revoked_at = now(), revoked_by = $2, revoked_reason = $3
WHERE id = $1::uuid AND status <> 'revoked'
RETURNING prefix
"""


def normalize_dsn(url: str) -> str:
    """asyncpg không nhận hậu tố driver kiểu SQLAlchemy (`postgresql+asyncpg://`)."""
    return re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", url)


def _record(row: asyncpg.Record) -> KeyRecord:
    return KeyRecord(
        key_id=row["key_id"],
        prefix=row["prefix"],
        secret_hmac=bytes(row["secret_hmac"]),
        name=row["name"],
        dept=row["dept"],
        allowed_models=tuple(row["allowed_models"]),
        rpm=row["rpm"],
        tpm=row["tpm"],
        max_concurrency=row["max_concurrency"],
        trust_end_user_token=row["trust_end_user_token"],
        expose_debug=row["expose_debug"],
        status=row["status"],
        expires_at=row["expires_at"],
    )


class PostgresKeyStore(KeyStore):
    def __init__(self, dsn: str, clock: Clock, *, pool: Any | None = None) -> None:
        self._dsn = normalize_dsn(dsn)
        self._clock = clock
        self._pool: Any = pool
        self._lock = asyncio.Lock()
        self._l1: dict[str, tuple[float, KeyRecord | None]] = {}

    async def _get_pool(self) -> Any:
        if self._pool is None:
            async with self._lock:
                if self._pool is None:
                    self._pool = await asyncpg.create_pool(
                        self._dsn, min_size=1, max_size=10, command_timeout=5
                    )
        return self._pool

    def _l1_put(self, prefix: str, rec: KeyRecord | None) -> None:
        if len(self._l1) >= L1_MAXSIZE:
            self._l1.pop(next(iter(self._l1)))
        ttl = L1_TTL_S if rec else L1_NEG_TTL_S
        self._l1[prefix] = (self._clock.monotonic() + ttl, rec)

    async def _fetch(self, prefix: str) -> KeyRecord | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(KEY_SQL, prefix)
        return _record(row) if row else None

    async def lookup(self, prefix: str) -> KeyRecord | None:
        hit = self._l1.get(prefix)
        if hit and hit[0] > self._clock.monotonic():
            return hit[1]
        rec = await self._fetch(prefix)
        self._l1_put(prefix, rec)
        return rec

    async def create(self, new: NewKey, actor: str) -> KeyRecord:
        pool = await self._get_pool()
        try:
            await pool.execute(
                INSERT_SQL,
                new.prefix,
                new.secret_hmac,
                new.name,
                new.owner_type,
                new.owner_ref,
                new.dept,
                list(new.allowed_models),
                new.rpm,
                new.tpm,
                new.max_concurrency,
                new.trust_end_user_token,
                new.expose_debug,
                actor,
                new.expires_at,
            )
        except asyncpg.UniqueViolationError:
            raise KeyAlreadyExists(new.prefix) from None
        self._l1.pop(new.prefix, None)  # xoá negative cache
        rec = await self._fetch(new.prefix)
        if rec is None:  # pragma: no cover - vừa insert xong
            raise KeyNotFound(new.prefix)
        return rec

    async def revoke(self, key_id: str, actor: str, reason: str) -> None:
        try:
            uuid.UUID(key_id)
        except ValueError:
            raise KeyNotFound(key_id) from None
        pool = await self._get_pool()
        row = await pool.fetchrow(REVOKE_SQL, key_id, actor, reason)
        if row is None:
            raise KeyNotFound(key_id)
        self._l1.pop(row["prefix"], None)

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
