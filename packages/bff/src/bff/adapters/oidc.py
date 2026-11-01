"""OidcClient: authorize URL, đổi code, refresh, revoke, end_session (07 §2.3).

Chỉ nói chuyện qua endpoint OIDC chuẩn (discovery lấy từ settings); không tên vendor trong mã.
Client `chat-ui` là confidential, `client_secret_basic`, PKCE S256.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any
from urllib.parse import urlencode

from acme_common.http import HttpError, RetryingHttpClient

from ..services.crypto import b64u, b64u_decode


class OidcUnavailable(Exception):
    """IdP không phản hồi / trả lỗi 5xx / discovery hỏng."""


class OidcInvalidGrant(Exception):
    """Code hoặc refresh token không còn hợp lệ."""


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = b64u(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def claims_of_verified(token: str) -> dict[str, Any]:
    """Đọc payload của JWT **đã được `TokenVerifier` xác minh** (không dùng để cấp quyền)."""
    try:
        payload = json.loads(b64u_decode(token.split(".")[1]))
    except (IndexError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class OidcClient:
    def __init__(
        self,
        http: RetryingHttpClient,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        post_logout_redirect_uri: str,
        token_url: str | None = None,
        scope: str = "openid profile",
    ) -> None:
        self._http = http
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._secret = client_secret
        self._redirect_uri = redirect_uri
        self._post_logout = post_logout_redirect_uri
        self._token_url = token_url
        self._scope = scope
        self._discovery: dict[str, Any] | None = None

    async def discovery(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._discovery is not None and not refresh:
            return self._discovery
        try:
            resp = await self._http.get(f"{self._issuer}/.well-known/openid-configuration")
            data = resp.json()
        except (HttpError, ValueError):
            raise OidcUnavailable("discovery") from None
        if resp.status_code != 200 or not isinstance(data, dict):
            raise OidcUnavailable("discovery")
        self._discovery = data
        return data

    async def _endpoint(self, name: str) -> str:
        value = (await self.discovery()).get(name)
        if not isinstance(value, str) or not value:
            raise OidcUnavailable(name)
        return value

    async def authorize_url(self, *, state: str, nonce: str, challenge: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "scope": self._scope,
                "redirect_uri": self._redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{await self._endpoint('authorization_endpoint')}?{query}"

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        url = self._token_url or await self._endpoint("token_endpoint")
        try:
            resp = await self._http.post(url, data=data, auth=(self._client_id, self._secret))
        except HttpError:
            raise OidcUnavailable("token") from None
        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                raise OidcUnavailable("token") from None
            if isinstance(body, dict) and body.get("access_token"):
                return body
            raise OidcUnavailable("token")
        if resp.status_code in (400, 401):
            raise OidcInvalidGrant()
        raise OidcUnavailable("token")

    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": verifier,
            }
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def revoke(self, refresh_token: str) -> None:
        """Cố gắng tối đa; lỗi chỉ để caller log."""
        url = (await self.discovery()).get("revocation_endpoint")
        if not url:
            return
        await self._http.post(
            url,
            data={"token": refresh_token, "token_type_hint": "refresh_token"},
            auth=(self._client_id, self._secret),
        )

    async def end_session_url(self) -> str | None:
        """URL đăng xuất phía IdP. KHÔNG kèm `id_token_hint`: id_token không được xuống trình
        duyệt (DoD M1 5a); dùng `client_id` + `post_logout_redirect_uri` (RP-initiated logout)."""
        endpoint = (await self.discovery()).get("end_session_endpoint")
        if not endpoint:
            return None
        params = {"post_logout_redirect_uri": self._post_logout, "client_id": self._client_id}
        return f"{endpoint}?{urlencode(params)}"


__all__ = [
    "OidcClient",
    "OidcInvalidGrant",
    "OidcUnavailable",
    "claims_of_verified",
    "pkce_pair",
]
