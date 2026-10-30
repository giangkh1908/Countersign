"""AES-GCM seal/open + HKDF từ BFF_SESSION_KEY (07 §2.2, §2.3).

`k_enc` mã hoá các trường `*_enc` của phiên; `k_csrf` ký HMAC cookie CSRF.
Giá trị mã hoá: base64url(nonce12 || ciphertext), AAD = sid || tên trường.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class CryptoError(Exception):
    """Không giải mã được (khoá sai / dữ liệu bị sửa). Không kèm nội dung."""


def _derive(master: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)


class Crypto:
    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise ValueError("master key must be 32 bytes")
        self._aead = AESGCM(_derive(master_key, b"bff-session-enc-v1"))
        self._csrf_key = _derive(master_key, b"bff-session-csrf-v1")

    @staticmethod
    def _aad(sid: str, field: str) -> bytes:
        return f"{sid}|{field}".encode()

    def seal(self, plaintext: str, *, sid: str, field: str) -> str:
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, plaintext.encode(), self._aad(sid, field))
        return b64u(nonce + ct)

    def open(self, sealed: str, *, sid: str, field: str) -> str:
        try:
            raw = b64u_decode(sealed)
            return self._aead.decrypt(raw[:12], raw[12:], self._aad(sid, field)).decode()
        except (InvalidTag, ValueError):
            raise CryptoError("cannot decrypt") from None

    def csrf_for(self, sid: str) -> str:
        return b64u(hmac.new(self._csrf_key, sid.encode(), hashlib.sha256).digest())
