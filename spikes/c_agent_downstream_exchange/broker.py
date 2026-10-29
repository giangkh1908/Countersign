"""Prototype port TokenBroker (Ports & Adapters) - chi trong spike.

agent-service goi `token_for(user_token, audience, scopes)` de lay token cho ha nguon.
Nghiep vu chi biet port; vendor (Keycloak RFC 8693 / client_credentials) nam sau adapter.
"""
from __future__ import annotations

import abc
import asyncio
import base64
import json
import time
from dataclasses import dataclass, field

import httpx

GRANT_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TYPE_AT = "urn:ietf:params:oauth:token-type:access_token"


def decode_unverified(token: str) -> dict:
    """Spike only: ban that lay claims tu Principal da verify (khong decode tay)."""
    p = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


@dataclass(frozen=True)
class AccessToken:
    value: str
    audience: str
    scopes: frozenset[str]
    expires_at: float
    sub: str
    user_token: str | None = None  # phuong an B: user token gui kem qua header
    meta: dict = field(default_factory=dict, compare=False)  # issued_token_type, expires_in, refresh...

    def __repr__(self) -> str:  # khong bao gio in token tho
        return (f"AccessToken(aud={self.audience}, scopes={sorted(self.scopes)}, sub={self.sub}, "
                f"{self.value[:6]}...(len={len(self.value)}))")


class TokenExchangeError(Exception):
    def __init__(self, status: int, error: str, description: str):
        super().__init__(f"{status} {error}: {description}")
        self.status, self.error, self.description = status, error, description


class TokenBroker(abc.ABC):
    @abc.abstractmethod
    async def token_for(self, user_token: str, audience: str, scopes: frozenset[str]) -> AccessToken: ...


async def _post_token(http: httpx.AsyncClient, url: str, data: dict) -> dict:
    r = await http.post(url, data=data)
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code != 200:
        raise TokenExchangeError(r.status_code, body.get("error", "unknown"),
                                 body.get("error_description", r.text[:200]))
    return body


def _aud_list(claims: dict) -> list[str]:
    a = claims.get("aud", [])
    return [a] if isinstance(a, str) else list(a)


class KeycloakTokenExchangeBroker(TokenBroker):
    """RFC 8693 (Keycloak standard token exchange V2): doi user token -> token cho `audience`."""

    def __init__(self, token_url: str, client_id: str, client_secret: str,
                 http: httpx.AsyncClient | None = None):
        self._url, self._cid, self._secret = token_url, client_id, client_secret
        self._http = http or httpx.AsyncClient(timeout=10)  # dung lai ket noi (keep-alive)

    async def token_for(self, user_token: str, audience: str, scopes: frozenset[str]) -> AccessToken:
        data = {"grant_type": GRANT_EXCHANGE, "client_id": self._cid, "client_secret": self._secret,
                "subject_token": user_token, "subject_token_type": TYPE_AT,
                "requested_token_type": TYPE_AT, "audience": audience, "scope": " ".join(sorted(scopes))}
        body = await _post_token(self._http, self._url, data)
        c = decode_unverified(body["access_token"])
        meta = {"issued_token_type": body.get("issued_token_type"), "expires_in": body.get("expires_in"),
                "refresh_token": "refresh_token" in body, "scope": body.get("scope")}
        return AccessToken(body["access_token"], audience, frozenset(c.get("scope", "").split()),
                           float(c["exp"]), c["sub"], meta=meta)


class ClientCredentialsWithUserTokenBroker(TokenBroker):
    """Phuong an B: token dich vu (client_credentials cua agent-service) + user token de gui header."""

    def __init__(self, token_url: str, client_id: str, client_secret: str,
                 http: httpx.AsyncClient | None = None):
        self._url, self._cid, self._secret = token_url, client_id, client_secret
        self._http = http or httpx.AsyncClient(timeout=10)

    async def token_for(self, user_token: str, audience: str, scopes: frozenset[str]) -> AccessToken:
        data = {"grant_type": "client_credentials", "client_id": self._cid, "client_secret": self._secret,
                "scope": " ".join(sorted(scopes))}
        body = await _post_token(self._http, self._url, data)
        c = decode_unverified(body["access_token"])
        if audience not in _aud_list(c):
            raise TokenExchangeError(400, "audience_mismatch", f"token khong co aud={audience}: {c.get('aud')}")
        meta = {"expires_in": body.get("expires_in"), "refresh_token": "refresh_token" in body}
        return AccessToken(body["access_token"], audience, frozenset(c.get("scope", "").split()),
                           float(c["exp"]), c["sub"], user_token=user_token, meta=meta)


class CachingTokenBroker(TokenBroker):
    """Decorator cung port: cache theo (sub, audience, scopes), TTL = exp - skew, single-flight."""

    NO_CACHE_SCOPES = frozenset({"tickets:write"})  # token ghi: moi lan mot token

    def __init__(self, inner: TokenBroker, skew: float = 30.0):
        self._inner, self._skew = inner, skew
        self._cache: dict[tuple, AccessToken] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}
        self.hits = self.misses = 0

    async def token_for(self, user_token: str, audience: str, scopes: frozenset[str]) -> AccessToken:
        if scopes & self.NO_CACHE_SCOPES:
            self.misses += 1
            return await self._inner.token_for(user_token, audience, scopes)
        sub = decode_unverified(user_token)["sub"]  # spike: ban that lay tu Principal da verify
        key = (sub, audience, tuple(sorted(scopes)))
        t = self._cache.get(key)
        if t and t.expires_at - self._skew > time.time():
            self.hits += 1
            return t
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            t = self._cache.get(key)
            if t and t.expires_at - self._skew > time.time():
                self.hits += 1
                return t
            self.misses += 1
            t = await self._inner.token_for(user_token, audience, scopes)
            self._cache[key] = t
            return t
