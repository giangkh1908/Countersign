"""Adapter `es256_jwt` cho port `ApprovalSigner`. Khoá riêng ES256 từ file PEM mount (không log, không repr).

Claims theo contracts §4.1: `aud` suy từ `iss` của intent (approval chỉ dùng được ở MCP đã phát intent).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from acme_common.ports import Clock, Principal
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from ..ports import ApprovalSigner, ApprovalToken, SignerError, VerifiedIntent

APPROVAL_ISSUER = "acme-approval"
APPROVAL_TYP = "acme-approval+jwt"
# iss của intent -> aud của approval (hằng trong mã, 05 §5.5)
_AUD_BY_INTENT_ISS: dict[str, str] = {"tickets-mcp": "tickets-mcp"}


def load_ec_private_key(pem: bytes) -> ec.EllipticCurvePrivateKey:
    try:
        key = load_pem_private_key(pem, password=None)
    except (ValueError, TypeError):
        raise ValueError("approval signing key is not a valid PEM private key") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("approval signing key must be ES256 (P-256)")
    return key


class Es256JwtApprovalSigner(ApprovalSigner):
    def __init__(
        self, private_key_pem: bytes, key_id: str, clock: Clock, *, ttl_s: int = 120
    ) -> None:
        if not key_id:
            raise ValueError("APPROVAL_SIGNER_KEY_ID is required")
        if not 0 < ttl_s <= 120:
            raise ValueError(
                "APPROVAL_TTL_S must be in (0, 120]"
            )  # tickets-mcp kiểm exp-iat <= 120
        self._key = load_ec_private_key(private_key_pem)
        self._kid = key_id
        self._clock = clock
        self._ttl = ttl_s

    def sign(self, intent: VerifiedIntent, principal: Principal) -> ApprovalToken:
        aud = _AUD_BY_INTENT_ISS.get(intent.iss)
        if aud is None or intent.sub != principal.sub:
            raise SignerError("intent_mismatch", reason="iss" if aud is None else "sub")
        now = self._clock.now().astimezone(UTC)
        exp = now + timedelta(seconds=self._ttl)
        jti = str(uuid.uuid4())
        claims = {
            "iss": APPROVAL_ISSUER,
            "aud": aud,
            "sub": principal.sub,
            "intent_id": intent.intent_id,
            "intent_sha256": intent.sha256,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        token = jwt.encode(
            claims, self._key, algorithm="ES256", headers={"typ": APPROVAL_TYP, "kid": self._kid}
        )
        return ApprovalToken(
            token=token, jti=jti, expires_at=datetime.fromtimestamp(claims["exp"], UTC)
        )
