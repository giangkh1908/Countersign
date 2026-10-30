"""Adapter `es256_jws` cho port `IntentVerifier`.

Khoá công khai intent đọc từ `INTENT_PUBLIC_KEYS_DIR/<kid>.pem|.pub` (mỗi lần verify đọc lại,
nên xoá file = thu hồi `kid` ngay, thêm file = xoay khoá không cần khởi động lại).
Header `kid` lạ => từ chối, không fetch mạng. Tài liệu: contracts §4.1, 05 §5.2.
"""

from __future__ import annotations

import re
from pathlib import Path

import jwt
from acme_common.ports import Clock, Principal
from acme_common.services.canonical import intent_sha256
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from ..ports import IntentVerifier, RenderModel, SignerError, VerifiedIntent
from ..rendering import build_render_model

_KID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MAX_JWS_BYTES = 16 * 1024
_INTENT_TYP = "acme-intent+jws"


def _mismatch(reason: str) -> SignerError:
    return SignerError("intent_mismatch", reason=reason)


class Es256JwsIntentVerifier(IntentVerifier):
    def __init__(
        self,
        keys_dir: str | Path,
        clock: Clock,
        *,
        issuer: str = "tickets-mcp",
        audience: str = "approval-signer",
    ) -> None:
        self._dir = Path(keys_dir)
        self._clock = clock
        self._issuer = issuer
        self._audience = audience

    def _public_key(self, kid: str) -> ec.EllipticCurvePublicKey:
        if not _KID_RE.fullmatch(kid):
            raise _mismatch("kid")
        for ext in (".pem", ".pub"):
            path = self._dir / f"{kid}{ext}"
            if path.is_file():
                try:
                    key = load_pem_public_key(path.read_bytes())
                except (ValueError, UnsupportedAlgorithm, OSError):
                    raise _mismatch("kid") from None
                if isinstance(key, ec.EllipticCurvePublicKey) and isinstance(
                    key.curve, ec.SECP256R1
                ):
                    return key
                break
        raise _mismatch("kid")

    def verify_intent(self, intent_jws: str, principal: Principal) -> VerifiedIntent:
        if not isinstance(intent_jws, str) or not intent_jws or len(intent_jws) > _MAX_JWS_BYTES:
            raise SignerError("invalid_argument")
        try:
            header = jwt.get_unverified_header(intent_jws)
        except jwt.PyJWTError:
            raise SignerError("invalid_argument") from None
        if header.get("alg") != "ES256":
            raise _mismatch("alg")
        if header.get("typ") != _INTENT_TYP:
            raise _mismatch("typ")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise _mismatch("kid")
        key = self._public_key(kid)
        try:
            payload = jwt.decode(
                intent_jws,
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
        except jwt.InvalidSignatureError:
            raise _mismatch("signature") from None
        except jwt.PyJWTError:
            raise SignerError("invalid_argument") from None
        if payload.get("iss") != self._issuer:
            raise _mismatch("iss")
        if payload.get("aud") != self._audience:
            raise _mismatch("aud")
        if not isinstance(payload.get("intent_id"), str) or not isinstance(payload.get("sub"), str):
            raise _mismatch("format")
        if payload["sub"] != principal.sub:
            raise _mismatch("sub")
        exp, iat = payload.get("exp"), payload.get("iat")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (exp, iat)):
            raise _mismatch("format")
        if self._clock.now().timestamp() >= exp:
            raise SignerError("intent_expired")
        try:
            digest = intent_sha256(payload)
        except (ValueError, TypeError):  # float trong payload: không canonical hoá được
            raise SignerError("intent_unrenderable", fields=["payload"]) from None
        return VerifiedIntent(payload=payload, sha256=digest)

    def verify(self, intent_jws: str, principal: Principal) -> RenderModel:
        return build_render_model(self.verify_intent(intent_jws, principal), self._clock.now())
