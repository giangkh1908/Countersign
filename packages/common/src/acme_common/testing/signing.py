"""Helper ký JWT cho test: tự sinh khoá (ES256/RS256), JWKS giả qua `httpx.MockTransport`.

Chỉ dùng trong test; không bao giờ nạp khoá cố định hay secret thật.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

ISSUER = "https://idp.test/realms/acme"


class TestSigner:
    __test__ = False  # không phải test class của pytest

    def __init__(self, alg: str = "ES256", kid: str = "k1") -> None:
        if alg not in {"ES256", "RS256"}:
            raise ValueError("alg must be ES256 or RS256")
        self.alg, self.kid = alg, kid
        if alg == "ES256":
            self._key: Any = ec.generate_private_key(ec.SECP256R1())
            self._algo: Any = ECAlgorithm(ECAlgorithm.SHA256)
        else:
            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._algo = RSAAlgorithm(RSAAlgorithm.SHA256)

    def jwk(self) -> dict[str, Any]:
        jwk = json.loads(self._algo.to_jwk(self._key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": self.alg})
        return jwk

    def sign(self, claims: dict[str, Any], *, kid: str | None = None) -> str:
        return jwt.encode(claims, self._key, algorithm=self.alg, headers={"kid": kid or self.kid})


def make_claims(
    now: float,
    *,
    aud: str | list[str] = "agent-service",
    sub: str = "user-1",
    iss: str = ISSUER,
    azp: str | None = "chat-ui",
    scope: str = "agent:invoke",
    ttl_s: float = 300.0,
    **extra: Any,
) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": iss,
        "sub": sub,
        "aud": aud,
        "iat": int(now),
        "exp": int(now + ttl_s),
        "scope": scope,
        "dept": ["CS"],
        "clearance": 1,
        "roles": ["employee"],
    }
    if azp is not None:
        claims["azp"] = azp
    claims.update(extra)
    return claims


class FakeJwksEndpoint:
    """Phục vụ JWKS từ danh sách signer (đổi được để mô phỏng xoay khoá); đếm số lần gọi."""

    JWKS_URL = "https://idp.test/jwks"

    def __init__(self, signers: list[TestSigner]) -> None:
        self.signers = signers
        self.hits = 0
        self.fail = False

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.hits += 1
            if self.fail:
                return httpx.Response(503)
            return httpx.Response(200, json={"keys": [s.jwk() for s in self.signers]})

        return httpx.MockTransport(handler)
