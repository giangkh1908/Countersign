"""Adapter `es256_jws` cho port `IntentIssuer`: ký intent ES256 và lưu/chuyển trạng thái trong Redis.

Khoá `mcp:tickets:intent:{intent_id}` là HASH `{jws, sha256, sub, status, owner_jti, updated_at}`,
TTL = intent `exp` + 30s (contracts §6). Chuyển trạng thái bằng Lua CAS (docs/design/approval.md §2.3). `load`
verify lại chữ ký JWS bằng khoá công khai của chính tickets-mcp rồi băm lại payload, nên sửa Redis
không đổi được `args_canonical`.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import jwt
from acme_common.mcp.errors import ToolError
from acme_common.ports import Clock, Principal
from acme_common.services.canonical import canonical_json, intent_sha256
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from redis.exceptions import RedisError

from ..ports import (
    BackendUnavailable,
    CasResult,
    Draft,
    IntentInvalid,
    IntentIssuer,
    SignedIntent,
    StoredIntent,
)

INTENT_TYP = "acme-intent+jws"
INTENT_PREFIX = "mcp:tickets:intent:"
GRACE_S = 30
MAX_PAYLOAD_BYTES = 8192
STALE_COMMITTING_S = 30.0

# KEYS[1]=intent; ARGV: jti, now
_BEGIN_LUA = """
local st = redis.call('HGET', KEYS[1], 'status')
if not st then return {'missing', '', '0'} end
if st == 'pending' then
  redis.call('HSET', KEYS[1], 'status', 'committing', 'owner_jti', ARGV[1], 'updated_at', ARGV[2])
  return {'owned', ARGV[1], ARGV[2]}
end
local h = redis.call('HMGET', KEYS[1], 'owner_jti', 'updated_at')
return {st, h[1] or '', h[2] or '0'}
"""
# ARGV: jti, new, now  (chỉ owner kết thúc)
_FINISH_LUA = """
local h = redis.call('HMGET', KEYS[1], 'status', 'owner_jti')
if h[1] == 'committing' and h[2] == ARGV[1] then
  redis.call('HSET', KEYS[1], 'status', ARGV[2], 'updated_at', ARGV[3])
  return 1
end
return 0
"""
# ARGV: stale_owner_jti, new, now, stale_s
_RECOVER_LUA = """
local h = redis.call('HMGET', KEYS[1], 'status', 'owner_jti', 'updated_at')
if h[1] == 'committing' and h[2] == ARGV[1]
   and (tonumber(ARGV[3]) - tonumber(h[3] or '0')) > tonumber(ARGV[4]) then
  redis.call('HSET', KEYS[1], 'status', ARGV[2], 'updated_at', ARGV[3])
  return 1
end
return 0
"""


def load_ec_private_key(pem: bytes) -> ec.EllipticCurvePrivateKey:
    try:
        key = load_pem_private_key(pem, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise ValueError("intent signing key is not a valid PEM private key") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("intent signing key must be ES256 (P-256)")
    return key


def _s(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


def _num(x: float) -> str:
    return f"{x:.6f}"


class Es256JwsIntentIssuer(IntentIssuer):
    def __init__(
        self,
        redis: Any,
        *,
        private_key_pem: bytes,
        key_id: str,
        clock: Clock,
        ttl_s: int = 300,
        issuer: str = "tickets-mcp",
        audience: str = "approval-signer",
    ) -> None:
        if not key_id:
            raise ValueError("INTENT_KEY_ID is required")
        self._r = redis
        self._key = load_ec_private_key(private_key_pem)
        self._pub = self._key.public_key()
        self._kid = key_id
        self._clock = clock
        self._ttl = ttl_s
        self._iss = issuer
        self._aud = audience
        self._begin = redis.register_script(_BEGIN_LUA)
        self._finish = redis.register_script(_FINISH_LUA)
        self._recover = redis.register_script(_RECOVER_LUA)

    @classmethod
    def from_path(cls, redis: Any, *, private_key_path: str, **kw: Any) -> Es256JwsIntentIssuer:
        if not private_key_path:
            raise ValueError("INTENT_PRIVATE_KEY_PATH is required")
        return cls(redis, private_key_pem=Path(private_key_path).read_bytes(), **kw)

    # --- phát hành ---
    async def issue(
        self, op: str, args: Mapping[str, Any], principal: Principal, draft: Draft
    ) -> SignedIntent:
        now = self._clock.now()
        iat = int(now.timestamp())
        exp = iat + self._ttl
        intent_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "v": 1,
            "iss": self._iss,
            "aud": self._aud,
            "sub": principal.sub,
            "iat": iat,
            "exp": exp,
            "intent_id": intent_id,
            "op": op,
            "target": dict(draft.target),
            "before": dict(draft.before),
            "after": dict(draft.after),
            "args_canonical": canonical_json(dict(args)).decode("utf-8"),
            "risk_flags": list(draft.risk_flags),
        }
        if draft.expected_updated_at is not None:
            payload["expected_updated_at"] = draft.expected_updated_at
        if draft.risk is not None:
            payload["risk"] = draft.risk
        try:
            size = len(canonical_json(payload))
        except ValueError:
            raise ToolError("invalid_argument", "intent payload not canonicalizable") from None
        if size > MAX_PAYLOAD_BYTES:
            raise ToolError("invalid_argument", "intent too large")
        sha = intent_sha256(payload)
        jws = jwt.encode(
            payload, self._key, algorithm="ES256", headers={"typ": INTENT_TYP, "kid": self._kid}
        )
        key = INTENT_PREFIX + intent_id
        try:
            async with self._r.pipeline(transaction=True) as pipe:
                pipe.hset(
                    key,
                    mapping={
                        "jws": jws,
                        "sha256": sha,
                        "sub": principal.sub,
                        "status": "pending",
                        "owner_jti": "",
                        "updated_at": _num(now.timestamp()),
                    },
                )
                pipe.expire(key, self._ttl + GRACE_S)
                await pipe.execute()
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
        return SignedIntent(intent_id, jws, sha, exp, payload)

    # --- đọc lại + verify ---
    async def load(self, intent_id: str) -> StoredIntent | None:
        try:
            raw = await self._r.hgetall(INTENT_PREFIX + intent_id)
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
        if not raw:
            return None
        h = {_s(k): _s(v) for k, v in raw.items()}
        try:
            jws, sha, sub, status = h["jws"], h["sha256"], h["sub"], h["status"]
        except KeyError:
            raise IntentInvalid("format") from None
        if status not in ("pending", "committing", "committed", "failed"):
            raise IntentInvalid("status")
        payload = self._verify_jws(jws)
        if payload.get("intent_id") != intent_id or payload.get("sub") != sub:
            raise IntentInvalid("binding")
        try:
            digest = intent_sha256(payload)
        except (ValueError, TypeError):
            raise IntentInvalid("canonical") from None
        if not hmac.compare_digest(digest, sha):
            raise IntentInvalid("sha256")
        try:
            updated = float(h.get("updated_at") or 0)
        except ValueError:
            updated = 0.0
        return StoredIntent(
            intent_id=intent_id,
            jws=jws,
            sha256=sha,
            sub=sub,
            status=status,  # type: ignore[arg-type]
            owner_jti=h.get("owner_jti") or None,
            updated_at=updated,
            payload=payload,
        )

    def _verify_jws(self, jws: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(jws)
            if (
                header.get("alg") != "ES256"
                or header.get("typ") != INTENT_TYP
                or header.get("kid") != self._kid
            ):
                raise IntentInvalid("header")
            payload = jwt.decode(
                jws,
                self._pub,
                algorithms=["ES256"],
                options={
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except jwt.PyJWTError:
            raise IntentInvalid("signature") from None
        if payload.get("iss") != self._iss or not isinstance(payload.get("exp"), int):
            raise IntentInvalid("claims")
        return payload

    # --- chuyển trạng thái (Lua CAS) ---
    async def begin_commit(self, intent_id: str, jti: str) -> CasResult:
        now = _num(self._clock.now().timestamp())
        try:
            res = await self._begin(keys=[INTENT_PREFIX + intent_id], args=[jti, now])
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
        st, owner, upd = (_s(x) for x in res)
        return CasResult(st, owner or None, float(upd or 0))  # type: ignore[arg-type]

    async def finish_commit(
        self, intent_id: str, jti: str, new: Literal["committed", "failed"]
    ) -> bool:
        now = _num(self._clock.now().timestamp())
        try:
            res = await self._finish(keys=[INTENT_PREFIX + intent_id], args=[jti, new, now])
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
        return bool(int(res))

    async def recover_stale(
        self, intent_id: str, stale_owner_jti: str, new: Literal["committed", "failed"]
    ) -> bool:
        now = _num(self._clock.now().timestamp())
        try:
            res = await self._recover(
                keys=[INTENT_PREFIX + intent_id],
                args=[stale_owner_jti, new, now, str(STALE_COMMITTING_S)],
            )
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
        return bool(int(res))
