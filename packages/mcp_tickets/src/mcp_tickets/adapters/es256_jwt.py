"""Adapter `es256_jwt` cho port `ApprovalVerifier`.

Khoá công khai approval nằm ở file riêng (`APPROVAL_PUBLIC_KEY_PATH`), tách khỏi JWKS Keycloak;
`alg` cứng ES256, `kid` phải thuộc tập tin cậy. Hết hạn tính theo `Clock` (test dùng FakeClock).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import jwt
from acme_common.ports import Clock, Principal
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from ..ports import Approval, ApprovalRejected, ApprovalVerifier

APPROVAL_TYP = "acme-approval+jwt"
APPROVAL_ISS = "acme-approval"
_KID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_IAT_SKEW_S = 5


def load_ec_public_key(pem: bytes) -> ec.EllipticCurvePublicKey:
    try:
        key = load_pem_public_key(pem)
    except (ValueError, UnsupportedAlgorithm):
        raise ValueError("approval public key is not a valid PEM public key") from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("approval public key must be ES256 (P-256)")
    return key


def load_trusted_keys(path: str, default_kid: str) -> dict[str, ec.EllipticCurvePublicKey]:
    """`path` là file PEM (kid = `default_kid`) hoặc thư mục chứa `<kid>.pem`."""
    if not path:
        raise ValueError("APPROVAL_PUBLIC_KEY_PATH is required")
    p = Path(path)
    if p.is_dir():
        keys = {
            f.stem: load_ec_public_key(f.read_bytes())
            for f in sorted(p.iterdir())
            if f.suffix in (".pem", ".pub") and _KID_RE.fullmatch(f.stem)
        }
        if not keys:
            raise ValueError("no approval public keys found")
        return keys
    return {default_kid: load_ec_public_key(p.read_bytes())}


class Es256JwtApprovalVerifier(ApprovalVerifier):
    def __init__(
        self,
        keys: Mapping[str, ec.EllipticCurvePublicKey],
        clock: Clock,
        *,
        audience: str = "tickets-mcp",
        max_ttl_s: int = 120,
    ) -> None:
        if not keys:
            raise ValueError("at least one approval public key is required")
        self._keys = dict(keys)
        self._clock = clock
        self._aud = audience
        self._max_ttl = max_ttl_s

    def verify(self, token: str, principal: Principal, intent_id: str) -> Approval:
        if not token:
            raise ApprovalRejected("approval_required")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise ApprovalRejected("approval_invalid", "malformed") from None
        if header.get("alg") != "ES256" or header.get("typ") != APPROVAL_TYP:
            raise ApprovalRejected("approval_invalid", "header")
        kid = header.get("kid")
        key = self._keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise ApprovalRejected("approval_invalid", "kid")
        try:
            c = jwt.decode(
                token,
                key,
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
            raise ApprovalRejected("approval_invalid", "signature") from None
        if c.get("iss") != APPROVAL_ISS:
            raise ApprovalRejected("approval_invalid", "iss")
        aud = c.get("aud")
        if not (aud == self._aud or (isinstance(aud, list) and self._aud in aud)):
            raise ApprovalRejected("approval_invalid", "aud")
        exp, iat = c.get("exp"), c.get("iat")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (exp, iat)):
            raise ApprovalRejected("approval_invalid", "claims")
        now = self._clock.now().timestamp()
        if exp - iat > self._max_ttl or iat > now + _IAT_SKEW_S:
            raise ApprovalRejected("approval_invalid", "ttl")
        if now >= exp:
            raise ApprovalRejected("approval_expired")
        if not isinstance(c.get("sub"), str) or c["sub"] != principal.sub:
            raise ApprovalRejected("approval_mismatch", "sub")
        jti, claim_intent, sha = c.get("jti"), c.get("intent_id"), c.get("intent_sha256")
        if not (
            isinstance(jti, str)
            and _UUID_RE.fullmatch(jti)
            and isinstance(claim_intent, str)
            and isinstance(sha, str)
            and len(sha) == 64
        ):
            raise ApprovalRejected("approval_invalid", "claims")
        if claim_intent != intent_id:
            raise ApprovalRejected("approval_mismatch", "intent_id")
        return Approval(jti=jti, intent_id=claim_intent, intent_sha256=sha)
