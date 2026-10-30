"""TokenService: token agent/signer theo phiên (D15), single-flight refresh (07 §2.4, §2.10).

Mỗi lần exchange chỉ MỘT audience. Token cache theo phiên trong `SessionStore` (không cache chéo
phiên). Token đăng nhập (`aud=chat-ui`) chỉ dùng làm subject cho exchange, không rời BFF.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar

from acme_common.ports import Clock, TokenBroker, TokenVerifier

from .errors import ApiError, UpstreamStatus
from .oidc import OidcClient, OidcInvalidGrant, OidcUnavailable
from .session import TOKEN_SLOTS, SessionData, SessionStore

log = logging.getLogger("bff.tokens")
_T = TypeVar("_T")

SCOPES_FOR: Mapping[str, tuple[str, ...]] = {
    "agent-service": ("agent:invoke",),
    "approval-signer": ("signer:approve",),
}
AGENT_AUD = "agent-service"
SIGNER_AUD = "approval-signer"

_REFRESH_BEFORE_S = 60
_REUSE_MARGIN_S = 30
_AGENT_TTL_CAP_S = 300


class TokenService:
    def __init__(
        self,
        broker: TokenBroker,
        verifier: TokenVerifier,
        oidc: OidcClient,
        store: SessionStore,
        clock: Clock,
        *,
        login_audience: str,
        signer_ttl_s: int,
    ) -> None:
        self._broker = broker
        self._verifier = verifier
        self._oidc = oidc
        self._store = store
        self._clock = clock
        self._login_aud = login_audience
        self._signer_ttl = signer_ttl_s

    def _now(self) -> float:
        return self._clock.now().timestamp()

    async def agent_token(self, s: SessionData) -> str:
        return await self._cached(s, "agent", AGENT_AUD, _AGENT_TTL_CAP_S)

    async def signer_token(self, s: SessionData) -> str:
        return await self._cached(s, "signer", SIGNER_AUD, self._signer_ttl)

    async def call(self, s: SessionData, slot: str, fn: Callable[[str], Awaitable[_T]]) -> _T:
        """Gọi upstream với token của `slot`; 401 thì exchange lại đúng một lần (07 §2.9)."""
        getter = self.agent_token if slot == "agent" else self.signer_token
        try:
            return await fn(await getter(s))
        except UpstreamStatus as exc:
            if exc.status != 401:
                raise
        await self.invalidate(s.sid, slot)
        fresh = await self._reload(s.sid)
        try:
            return await fn(await getter(fresh))
        except UpstreamStatus as exc:
            if exc.status == 401:
                raise ApiError(401, "session_expired") from None
            raise

    async def invalidate(self, sid: str, slot: str) -> None:
        enc, exp = TOKEN_SLOTS[slot]
        await self._store.update(sid, {}, drop=(enc, exp))

    def _fresh(self, s: SessionData, slot: str, margin: float) -> str | None:
        token, exp = s.token(slot)
        return token if token and exp - self._now() > margin else None

    async def _reload(self, sid: str) -> SessionData:
        fresh = await self._store.load(sid)
        if fresh is None:
            raise ApiError(401, "session_expired")
        return fresh

    async def _cached(self, s: SessionData, slot: str, audience: str, ttl_cap: float) -> str:
        if (tok := self._fresh(s, slot, _REUSE_MARGIN_S)) is not None:
            return tok
        async with self._store.single_flight(s.sid):
            s = await self._reload(s.sid)  # request khác có thể đã làm xong
            if (tok := self._fresh(s, slot, _REUSE_MARGIN_S)) is not None:
                return tok
            s = await self._ensure_login(s)
            subject = s.token("login")[0]
            if subject is None:
                raise ApiError(401, "session_expired")
            principal = await self._verifier.verify(subject, self._login_aud)
            issued = await self._broker.token_for(
                principal, subject, audience, SCOPES_FOR[audience]
            )
            exp = min(issued.expires_at, self._now() + ttl_cap)
            await self._store.update(
                s.sid, self._store.token_fields(s.sid, slot, issued.value, exp)
            )
            return issued.value

    async def _ensure_login(self, s: SessionData) -> SessionData:
        if self._fresh(s, "login", _REFRESH_BEFORE_S) is not None:
            return s
        refresh = s.open_field("refresh_token_enc")
        if not refresh:
            await self._store.destroy(s.sid)
            raise ApiError(401, "session_expired")
        try:
            tok = await self._oidc.refresh(refresh)
        except OidcInvalidGrant:
            await self._store.destroy(s.sid)
            raise ApiError(401, "session_expired") from None
        except OidcUnavailable:
            raise ApiError(502, "upstream_unavailable", True) from None  # không xoá phiên
        fields = self._store.token_fields(
            s.sid, "login", tok["access_token"], self._now() + float(tok.get("expires_in", 300))
        )
        # refresh token xoay vòng: ghi bản mới trong cùng một HSET nguyên tử
        fields["refresh_token_enc"] = s.sealed(
            "refresh_token_enc", tok.get("refresh_token", refresh)
        )
        if tok.get("id_token"):
            fields["id_token_enc"] = s.sealed("id_token_enc", tok["id_token"])
        drop = tuple(f for slot in ("agent", "signer") for f in TOKEN_SLOTS[slot])
        await self._store.update(s.sid, fields, drop=drop)
        return await self._reload(s.sid)
