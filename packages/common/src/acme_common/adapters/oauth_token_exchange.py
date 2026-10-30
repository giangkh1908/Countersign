"""Adapter `oauth_token_exchange` cho port `TokenBroker`. RFC 8693.
Milestone: M3.
Tài liệu: docs/design/00-contracts.md §9.2.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

import jwt

from ..http import HttpError, RetryingHttpClient
from ..ports.errors import TokenExchangeDenied, TokenServiceUnavailable
from ..ports.token_broker import TokenBroker
from ..ports.types import AccessToken, Principal

GRANT_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TYPE_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"

_ERROR_CODE = re.compile(r"^[a-z_]{1,40}$")


def _aud_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [v for v in value if isinstance(v, str)]
    return []


class OAuthTokenExchangeBroker(TokenBroker):
    """Đổi token người dùng lấy token cho đúng một audience (RFC 8693, mỗi request một audience).

    Hậu điều kiện ADR-005 (IdP không tự chặn): `aud == [audience]`, scope (trừ scope mặc định
    không phải quyền) ⊆ scope đã xin, `sub` trùng principal; sai thì raise, không trả token.
    Token đổi ra nhận trực tiếp từ IdP qua kênh đã xác thực client nên chỉ đọc claim, không
    verify lại chữ ký (resource server đích sẽ verify).
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        http: RetryingHttpClient,
        ignored_scopes: Iterable[str] = ("openid", "profile", "email", "offline_access"),
    ) -> None:
        self._url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._ignored = frozenset(ignored_scopes)

    async def token_for(
        self,
        principal: Principal,
        user_token: str,
        audience: str,
        scopes: Sequence[str],
    ) -> AccessToken:
        if not audience or any(c in audience for c in " ,"):
            raise ValueError("exactly one audience per exchange")
        requested = frozenset(scopes)
        data = {
            "grant_type": GRANT_EXCHANGE,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "subject_token": user_token,
            "subject_token_type": TYPE_ACCESS_TOKEN,
            "requested_token_type": TYPE_ACCESS_TOKEN,
            "audience": audience,
            "scope": " ".join(sorted(requested)),
        }
        try:
            resp = await self._http.post(self._url, data=data)
        except HttpError:
            raise TokenServiceUnavailable("token_endpoint") from None
        if resp.status_code != 200:
            raise TokenExchangeDenied(self._error_reason(resp), http_status=resp.status_code)
        try:
            access = resp.json()["access_token"]
            claims = jwt.decode(access, options={"verify_signature": False})
        except (ValueError, KeyError, TypeError, jwt.PyJWTError):
            raise TokenExchangeDenied("malformed_response") from None
        return self._check_postconditions(claims, access, principal, audience, requested)

    @staticmethod
    def _error_reason(resp: object) -> str:
        try:
            code = resp.json().get("error")  # type: ignore[attr-defined]
        except (ValueError, AttributeError):
            return "denied"
        return code if isinstance(code, str) and _ERROR_CODE.match(code) else "denied"

    def _check_postconditions(
        self,
        claims: dict[str, object],
        access: str,
        principal: Principal,
        audience: str,
        requested: frozenset[str],
    ) -> AccessToken:
        if _aud_list(claims.get("aud")) != [audience]:
            raise TokenExchangeDenied("audience_mismatch")
        scope_claim = claims.get("scope")
        granted = frozenset(scope_claim.split()) if isinstance(scope_claim, str) else frozenset()
        if not (granted - self._ignored) <= requested:
            raise TokenExchangeDenied("scope_escalation")
        sub, exp = claims.get("sub"), claims.get("exp")
        if sub != principal.sub:
            raise TokenExchangeDenied("subject_mismatch")
        if not isinstance(exp, int | float) or isinstance(exp, bool):
            raise TokenExchangeDenied("malformed_response")
        return AccessToken(
            value=access,
            audience=audience,
            scopes=granted - self._ignored,
            expires_at=float(exp),
            sub=principal.sub,
        )
