"""Xác thực: API key (tra theo prefix, HMAC + pepper, so sánh hằng thời gian) và user token (01 §3)."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

from acme_common.ports import Clock, Principal, TokenInvalid, TokenServiceUnavailable, TokenVerifier

from ..ports.key_store import KeyStore
from ..ports.types import KeyRecord
from .errors import GatewayError
from .key_admin import parse_key

log = logging.getLogger("gateway.auth")

END_USER_AUDIENCE = "llm-gateway"
_DUMMY = hmac.new(b"x" * 32, b"dummy", hashlib.sha256).digest()


@dataclass(frozen=True, slots=True)
class Caller:
    key: KeyRecord
    user: Principal | None  # có khi key được tin và header user token hợp lệ

    @property
    def dept(self) -> str:
        """Phòng ban hiệu lực: dept chính của user nếu có, ngược lại dept của key."""
        if self.user and self.user.dept:
            return self.user.dept[0]
        return self.key.dept

    @property
    def end_user_sub(self) -> str | None:
        return self.user.sub if self.user else None


class AuthService:
    def __init__(
        self,
        keys: KeyStore,
        verifier: TokenVerifier,
        clock: Clock,
        pepper: bytes,
        pepper_prev: bytes | None = None,
    ) -> None:
        self._keys = keys
        self._verifier = verifier
        self._clock = clock
        self._peppers = [p for p in (pepper, pepper_prev) if p]
        self.untrusted_user_token_total = 0

    async def authenticate(self, authorization: str | None, user_token: str | None) -> Caller:
        if not authorization or not authorization.startswith("Bearer "):
            raise GatewayError("invalid_api_key")
        parsed = parse_key(authorization[7:])
        if parsed is None:
            raise GatewayError("invalid_api_key")  # không chạm store
        prefix, secret = parsed

        try:
            rec = await self._keys.lookup(prefix)
        except GatewayError:
            raise
        except Exception:
            log.exception("key store lookup failed")
            raise GatewayError("service_unavailable") from None

        expected = rec.secret_hmac if rec else _DUMMY
        ok = False
        for pepper in self._peppers:  # luôn tính HMAC để thời gian ~ bằng nhau
            got = hmac.new(pepper, secret, hashlib.sha256).digest()
            ok = hmac.compare_digest(got, expected) or ok
        if rec is None or not ok:
            raise GatewayError("invalid_api_key")  # cùng thông điệp: không lộ prefix tồn tại
        if rec.status == "revoked":
            raise GatewayError("key_revoked")
        if rec.status == "expired" or (rec.expires_at and rec.expires_at <= self._clock.now()):
            raise GatewayError("key_expired")

        user: Principal | None = None
        if user_token:
            if not rec.trust_end_user_token:
                # Không nâng quyền, không đổi dept; chỉ đếm và cảnh báo (không log token).
                self.untrusted_user_token_total += 1
                log.warning(
                    "x-acme-user-token ignored for untrusted key",
                    extra={"fields": {"key_id": rec.key_id}},
                )
            else:
                try:
                    user = await self._verifier.verify(user_token, END_USER_AUDIENCE)
                except TokenInvalid:
                    raise GatewayError("invalid_end_user_token") from None
                except TokenServiceUnavailable:
                    raise GatewayError("service_unavailable") from None
        return Caller(key=rec, user=user)
