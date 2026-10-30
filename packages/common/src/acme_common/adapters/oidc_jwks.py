"""Adapter `oidc_jwks` cho port `TokenVerifier`. Chuẩn OIDC/JWKS; tên Keycloak chỉ ở settings.
Milestone: M1.
Tài liệu: docs/design/00-contracts.md §9.2.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

import jwt

from ..http import HttpError, RetryingHttpClient
from ..ports.clock import Clock
from ..ports.errors import TokenInvalid, TokenServiceUnavailable
from ..ports.token_verifier import TokenVerifier
from ..ports.types import Principal


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [v for v in value if isinstance(v, str)]
    return []


class OidcJwksTokenVerifier(TokenVerifier):
    """Xác minh JWT bằng JWKS của IdP: chữ ký, `iss` (so khớp chuỗi chính xác), `aud`, `exp`, `azp`, scope.

    Thời gian lấy từ `Clock` (PyJWT chỉ dùng để kiểm chữ ký). JWKS được cache theo TTL; gặp `kid`
    lạ thì nạp lại (xoay khoá), nhưng không quá một lần mỗi `min_refetch_s` để chống bị ép gọi IdP.
    """

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        http: RetryingHttpClient,
        clock: Clock,
        algorithms: Iterable[str] = ("RS256", "ES256"),
        allowed_azp: Iterable[str] = (),
        required_scopes: Iterable[str] = (),
        required_claims: Iterable[str] = ("sub",),
        leeway_s: float = 0.0,
        jwks_ttl_s: float = 300.0,
        min_refetch_s: float = 30.0,
    ) -> None:
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._http = http
        self._clock = clock
        self._algorithms = tuple(algorithms)
        self._allowed_azp = frozenset(allowed_azp)
        self._required_scopes = frozenset(required_scopes)
        self._required_claims = tuple(required_claims)
        self._leeway = leeway_s
        self._ttl = jwks_ttl_s
        self._min_refetch = min_refetch_s
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._attempted_at: float | None = None
        self._lock = asyncio.Lock()

    # --- JWKS cache ---
    async def _refresh(self) -> None:
        self._attempted_at = self._clock.monotonic()
        try:
            resp = await self._http.get(self._jwks_url)
            if resp.status_code != 200:
                raise TokenServiceUnavailable("jwks")
            doc = resp.json()
        except (HttpError, ValueError):
            raise TokenServiceUnavailable("jwks") from None
        keys: dict[str, jwt.PyJWK] = {}
        for jwk in doc.get("keys", []) if isinstance(doc, dict) else []:
            if not isinstance(jwk, dict) or jwk.get("use", "sig") != "sig" or "kid" not in jwk:
                continue
            try:
                keys[jwk["kid"]] = jwt.PyJWK(jwk)
            except jwt.PyJWTError:
                continue  # khoá loại không hỗ trợ: bỏ qua
        self._keys = keys
        self._fetched_at = self._attempted_at

    def _cached(self, kid: str) -> jwt.PyJWK | None:
        fresh = (
            self._fetched_at is not None and self._clock.monotonic() - self._fetched_at < self._ttl
        )
        return self._keys.get(kid) if fresh else None

    async def _key_for(self, kid: str) -> jwt.PyJWK:
        if (key := self._cached(kid)) is not None:
            return key
        async with self._lock:
            if (key := self._cached(kid)) is not None:
                return key
            last = self._attempted_at
            if last is None or self._clock.monotonic() - last >= self._min_refetch:
                try:
                    await self._refresh()
                except TokenServiceUnavailable:
                    if kid not in self._keys:
                        raise
            key = self._keys.get(kid)
        if key is None:
            raise TokenInvalid("unknown_kid")
        return key

    # --- verify ---
    async def verify(self, token: str, audience: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise TokenInvalid("malformed") from None
        alg, kid = header.get("alg"), header.get("kid")
        if alg not in self._algorithms:
            raise TokenInvalid("bad_algorithm")
        if not isinstance(kid, str):
            raise TokenInvalid("malformed")
        key = await self._key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[alg],
                options={
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except jwt.InvalidSignatureError:
            raise TokenInvalid("bad_signature") from None
        except jwt.PyJWTError:
            raise TokenInvalid("malformed") from None
        return self._check_claims(claims, audience)

    def _check_claims(self, claims: dict[str, Any], audience: str) -> Principal:
        now = self._clock.now().timestamp()
        exp = claims.get("exp")
        if not isinstance(exp, int | float) or isinstance(exp, bool):
            raise TokenInvalid("malformed")
        if exp <= now - self._leeway:
            raise TokenInvalid("expired")
        nbf = claims.get("nbf")
        if isinstance(nbf, int | float) and nbf > now + self._leeway:
            raise TokenInvalid("not_yet_valid")
        if claims.get("iss") != self._issuer:
            raise TokenInvalid("bad_issuer")
        aud = _as_list(claims.get("aud"))
        if audience not in aud:
            raise TokenInvalid("bad_audience")
        azp = claims.get("azp")
        if self._allowed_azp and azp not in self._allowed_azp:
            raise TokenInvalid("bad_azp")
        scope_claim = claims.get("scope")
        scopes = frozenset(scope_claim.split()) if isinstance(scope_claim, str) else frozenset()
        if not self._required_scopes <= scopes:
            raise TokenInvalid("missing_scope")
        for name in self._required_claims:
            if claims.get(name) in (None, "", []):
                raise TokenInvalid("malformed")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise TokenInvalid("malformed")
        clearance = claims.get("clearance")
        roles = claims.get("roles")
        if roles is None and isinstance(claims.get("realm_access"), dict):
            roles = claims["realm_access"].get("roles")
        sid = claims.get("sid")
        return Principal(
            sub=sub,
            audience=tuple(aud),
            azp=azp if isinstance(azp, str) else None,
            scopes=scopes,
            expires_at=float(exp),
            sid=sid if isinstance(sid, str) else None,
            dept=tuple(_as_list(claims.get("dept"))),
            clearance=int(clearance)
            if isinstance(clearance, int | str) and str(clearance).isdigit()
            else None,
            roles=tuple(_as_list(roles)),
        )
