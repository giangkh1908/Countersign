"""AuthService: bắt đầu đăng nhập, xử lý callback, đăng xuất (07 §2.3, §2.10)."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
from dataclasses import dataclass

from acme_common.http import HttpError
from acme_common.ports import Clock, TokenInvalid, TokenServiceUnavailable, TokenVerifier

from ..clients.agent_client import AgentClient
from .oidc import OidcClient, OidcInvalidGrant, OidcUnavailable, claims_of_verified, pkce_pair
from .session import SessionData, SessionStore
from .tokens import TokenService

log = logging.getLogger("bff.auth")


class LoginFailed(Exception):
    """Đăng nhập thất bại. `code` là mã chung đưa lên `/login-error?code=`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def safe_return_to(value: str | None) -> str:
    """Chỉ nhận đường dẫn nội bộ: bắt đầu bằng `/`, không `//`, không `\\`."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if any(ord(c) < 0x20 for c in value):
        return "/"
    return value


@dataclass
class LoginStart:
    state: str
    authorize_url: str


@dataclass
class LoginDone:
    sid: str
    csrf: str
    return_to: str


class AuthService:
    def __init__(
        self,
        store: SessionStore,
        oidc: OidcClient,
        verifier: TokenVerifier,
        tokens: TokenService,
        agent: AgentClient,
        clock: Clock,
        *,
        client_id: str,
    ) -> None:
        self._store = store
        self._oidc = oidc
        self._verifier = verifier
        self._tokens = tokens
        self._agent = agent
        self._clock = clock
        self._client_id = client_id

    async def start(self, return_to: str | None) -> LoginStart:
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        verifier, challenge = pkce_pair()
        try:
            url = await self._oidc.authorize_url(state=state, nonce=nonce, challenge=challenge)
        except OidcUnavailable:
            raise LoginFailed("idp_unavailable") from None
        await self._store.login_put(
            state,
            {
                "verifier": verifier,
                "nonce": nonce,
                "return_to": safe_return_to(return_to),
                "created_at": int(self._clock.now().timestamp()),
            },
        )
        return LoginStart(state, url)

    async def complete(self, code: str, state: str, cookie_state: str | None) -> LoginDone:
        if not code or not state or not cookie_state:
            raise LoginFailed("state_mismatch")
        if not hmac.compare_digest(cookie_state.encode(), state.encode()):
            raise LoginFailed("state_mismatch")
        pending = await self._store.login_pop(state)
        if pending is None:
            raise LoginFailed("state_mismatch")
        try:
            tok = await self._oidc.exchange_code(code, pending["verifier"])
        except OidcInvalidGrant:
            raise LoginFailed("token_error") from None
        except OidcUnavailable:
            raise LoginFailed("idp_unavailable") from None
        try:
            access, id_token = tok["access_token"], tok.get("id_token")
            principal = await self._verifier.verify(access, self._client_id)
            if not id_token:
                raise LoginFailed("token_error")
            id_principal = await self._verifier.verify(id_token, self._client_id)
        except TokenInvalid:
            raise LoginFailed("token_error") from None
        except TokenServiceUnavailable:
            raise LoginFailed("idp_unavailable") from None
        id_claims = claims_of_verified(id_token)  # đã qua verifier
        nonce = id_claims.get("nonce")
        if not (
            isinstance(nonce, str)
            and hmac.compare_digest(nonce.encode(), pending["nonce"].encode())
        ):
            raise LoginFailed("token_error")
        if id_principal.sub != principal.sub:
            raise LoginFailed("token_error")

        now = self._clock.now().timestamp()
        sid = self._store.new_sid()  # luôn sinh mới (chống session fixation)
        csrf = self._store.crypto.csrf_for(sid)
        user = {
            "name": id_claims.get("name") or id_claims.get("preferred_username") or "",
            "email": id_claims.get("email") or "",
            "roles": list(principal.roles),
            "depts": list(principal.dept),
            "clearance": principal.clearance if principal.clearance is not None else 0,
        }
        fields = {
            "v": "1",
            "sub": principal.sub,
            "user": json.dumps(user, ensure_ascii=False),
            "created_at": str(int(now)),
            "csrf": csrf,
            **self._store.token_fields(
                sid, "login", access, now + float(tok.get("expires_in", 300))
            ),
            "id_token_enc": self._store.crypto.seal(id_token, sid=sid, field="id_token_enc"),
        }
        if tok.get("refresh_token"):
            fields["refresh_token_enc"] = self._store.crypto.seal(
                tok["refresh_token"], sid=sid, field="refresh_token_enc"
            )
        await self._store.create(sid, fields)
        return LoginDone(sid, csrf, safe_return_to(pending.get("return_to")))

    async def logout(self, s: SessionData) -> str:
        """Thu hồi (cố gắng tối đa), evict cache agent, xoá phiên; trả URL end_session hoặc `/`."""
        refresh = s.open_field("refresh_token_enc")
        if refresh:
            try:
                await self._oidc.revoke(refresh)
            except (HttpError, OidcUnavailable):
                log.warning("revoke_failed")
        try:
            await self._tokens.call(s, "agent", lambda tok: self._agent.evict(tok))
        except Exception:  # evict/exchange lỗi không được chặn đăng xuất
            log.warning("evict_failed")
        await self._store.destroy(s.sid)
        try:
            return await self._oidc.end_session_url() or "/"
        except OidcUnavailable:
            return "/"
