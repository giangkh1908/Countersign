"""SessionStore (Redis HASH `bff:sess:{sid}`) và SessionData (contracts §6).

User Redis `bff` chỉ có lệnh đơn (không MULTI/WATCH/EVAL): chỉ dùng GET/SET NX EX/HSET/HGETALL/
HDEL/EXPIRE/INCR/DECR/SADD/SISMEMBER/DEL/SCAN. Mọi trường `*_enc` là AES-GCM (AAD = sid + tên trường).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import secrets
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from acme_common.ports import Clock
from redis.asyncio import Redis

from .crypto import Crypto

MAX_PENDING = 5

# slot token -> (trường mã hoá, trường hết hạn)
TOKEN_SLOTS: dict[str, tuple[str, str]] = {
    "login": ("access_enc", "access_exp"),
    "agent": ("agent_enc", "agent_exp"),
    "signer": ("signer_token", "signer_exp"),
}


def sess_key(sid: str) -> str:
    return f"bff:sess:{sid}"


def user_hash(sub: str) -> str:
    return hashlib.sha256(sub.encode()).hexdigest()[:16]


@dataclass
class SessionData:
    sid: str
    raw: dict[str, str]
    crypto: Crypto

    @property
    def sub(self) -> str:
        return self.raw["sub"]

    @property
    def created_at(self) -> int:
        return int(self.raw["created_at"])

    @property
    def csrf(self) -> str:
        return self.raw.get("csrf", "")

    @property
    def user(self) -> dict[str, Any]:
        try:
            data = json.loads(self.raw.get("user", "{}"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def open_field(self, field: str) -> str | None:
        sealed = self.raw.get(field)
        return self.crypto.open(sealed, sid=self.sid, field=field) if sealed else None

    def token(self, slot: str) -> tuple[str | None, float]:
        enc, exp = TOKEN_SLOTS[slot]
        value = self.open_field(enc)
        return value, float(self.raw.get(exp, "0") or 0)

    def sealed(self, field: str, plaintext: str) -> str:
        return self.crypto.seal(plaintext, sid=self.sid, field=field)


class SessionStore:
    def __init__(self, redis: Redis, crypto: Crypto, clock: Clock, *, idle_s: int, abs_s: int):
        self.redis = redis
        self.crypto = crypto
        self.clock = clock
        self.idle_s = idle_s
        self.abs_s = abs_s
        self._locks: dict[str, asyncio.Lock] = {}

    def now(self) -> float:
        return self.clock.now().timestamp()

    # --- vòng đời phiên ---
    @staticmethod
    def new_sid() -> str:
        return secrets.token_urlsafe(32)

    def ttl_for(self, created_at: int) -> int:
        return max(1, min(self.idle_s, int(created_at + self.abs_s - self.now())))

    async def create(self, sid: str, fields: Mapping[str, str]) -> None:
        key = sess_key(sid)
        await self.redis.hset(key, mapping=dict(fields))
        await self.redis.expire(key, self.ttl_for(int(fields["created_at"])))

    async def load(self, sid: str) -> SessionData | None:
        if not sid:
            return None
        raw = await self.redis.hgetall(sess_key(sid))
        if not raw or "created_at" not in raw:
            return None
        created = int(raw["created_at"])
        if self.now() > created + self.abs_s:
            await self.destroy(sid)
            return None
        await self._touch(sid, created)
        return SessionData(sid, raw, self.crypto)

    async def _touch(self, sid: str, created_at: int) -> None:
        ttl = self.ttl_for(created_at)
        await self.redis.expire(sess_key(sid), ttl)
        await self.redis.expire(f"{sess_key(sid)}:pend", ttl)

    async def update(self, sid: str, fields: Mapping[str, str], drop: tuple[str, ...] = ()) -> None:
        key = sess_key(sid)
        if fields:
            await self.redis.hset(key, mapping=dict(fields))
        if drop:
            await self.redis.hdel(key, *drop)

    async def destroy(self, sid: str) -> None:
        keys = [k async for k in self.redis.scan_iter(match=f"{sess_key(sid)}*")]
        if keys:
            await self.redis.delete(*keys)

    # --- trạng thái đăng nhập (dùng một lần) ---
    async def login_put(self, state: str, data: Mapping[str, Any], ttl_s: int = 600) -> None:
        await self.redis.set(f"bff:sess:login:{state}", json.dumps(dict(data)), ex=ttl_s)

    async def login_pop(self, state: str) -> dict[str, Any] | None:
        raw = await self.redis.getdel(f"bff:sess:login:{state}")
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None

    # --- token slot ---
    def token_fields(self, sid: str, slot: str, value: str, exp: float) -> dict[str, str]:
        enc, exp_field = TOKEN_SLOTS[slot]
        return {enc: self.crypto.seal(value, sid=sid, field=enc), exp_field: str(int(exp))}

    # --- single flight ---
    @contextlib.asynccontextmanager
    async def single_flight(self, sid: str, *, wait_s: float = 3.0) -> AsyncIterator[None]:
        local = self._locks.setdefault(sid, asyncio.Lock())
        async with local:
            key = f"{sess_key(sid)}:lock"
            got = False
            deadline = asyncio.get_running_loop().time() + wait_s
            while True:
                got = bool(await self.redis.set(key, "1", nx=True, px=10000))
                if got or asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.05)
            try:
                yield
            finally:
                if got:
                    await self.redis.delete(key)

    # --- pend (interrupt đã nhận từ agent) ---
    async def pend_put(self, sid: str, interrupt_id: str, value: dict[str, Any]) -> None:
        key = f"{sess_key(sid)}:pend"
        if await self.redis.hlen(key) >= MAX_PENDING and not await self.redis.hexists(
            key, interrupt_id
        ):
            await self.redis.delete(key)
        await self.redis.hset(key, interrupt_id, json.dumps(value, separators=(",", ":")))
        await self.redis.expire(key, self.idle_s)

    async def pend_get(self, sid: str, interrupt_id: str) -> dict[str, Any] | None:
        raw = await self.redis.hget(f"{sess_key(sid)}:pend", interrupt_id)
        return json.loads(raw) if raw else None

    async def pend_update(self, sid: str, interrupt_id: str, **changes: Any) -> None:
        cur = await self.pend_get(sid, interrupt_id)
        if cur is not None:
            cur.update(changes)
            await self.redis.hset(
                f"{sess_key(sid)}:pend", interrupt_id, json.dumps(cur, separators=(",", ":"))
            )

    async def pend_delete(self, sid: str, interrupt_id: str) -> None:
        await self.redis.hdel(f"{sess_key(sid)}:pend", interrupt_id)

    # --- danh sách từ chối ---
    async def rej_add(self, sid: str, ttl_s: int, *values: str) -> None:
        key = f"{sess_key(sid)}:rej"
        await self.redis.sadd(key, *[v for v in values if v])
        await self.redis.expire(key, ttl_s)

    async def rej_has(self, sid: str, value: str) -> bool:
        return bool(await self.redis.sismember(f"{sess_key(sid)}:rej", value))

    # --- gate chống bấm đúp ---
    async def gate(self, sid: str, interrupt_id: str) -> bool:
        return bool(
            await self.redis.set(f"{sess_key(sid)}:gate:{interrupt_id}", "1", nx=True, ex=150)
        )

    async def gate_release(self, sid: str, interrupt_id: str) -> None:
        await self.redis.delete(f"{sess_key(sid)}:gate:{interrupt_id}")

    # --- bộ đếm có TTL ---
    async def incr(self, key: str, ttl_s: int) -> int:
        n = int(await self.redis.incr(key))
        if n == 1:
            await self.redis.expire(key, ttl_s)
        return n

    async def decr(self, key: str) -> None:
        n = int(await self.redis.decr(key))
        if n <= 0:
            await self.redis.delete(key)

    async def ttl(self, key: str) -> int:
        return max(1, int(await self.redis.ttl(key)))
