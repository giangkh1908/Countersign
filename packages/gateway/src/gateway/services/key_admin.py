"""Sinh và băm API key (01 §3.1). Format: `sk-acme-<prefix12>.<secret43>`; chỉ lưu HMAC của secret."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime

from ..ports.types import NewKey

ALPHABET = string.ascii_letters + string.digits
KEY_RE = re.compile(rb"^sk-acme-([A-Za-z0-9]{12})\.([A-Za-z0-9_-]{43})$")
MIN_PEPPER_BYTES = 32


def hmac_secret(secret: bytes, pepper: bytes) -> bytes:
    """HMAC-SHA256(key=pepper, msg=secret) (contracts §3.1)."""
    return hmac.new(pepper, secret, hashlib.sha256).digest()


def parse_key(raw: str) -> tuple[str, bytes] | None:
    """Trả (prefix, secret) nếu đúng định dạng; None nếu sai (không chạm store)."""
    m = KEY_RE.match(raw.encode("ascii", "ignore"))
    if not m:
        return None
    return m.group(1).decode(), m.group(2)


@dataclass(frozen=True, slots=True)
class IssuedKey:
    plaintext: str  # trả cho người dùng đúng một lần, không lưu
    new: NewKey


def issue_key(
    pepper: bytes,
    *,
    name: str,
    owner_type: str,
    owner_ref: str,
    dept: str,
    allowed_models: tuple[str, ...],
    rpm: int,
    tpm: int,
    max_concurrency: int = 8,
    trust_end_user_token: bool = False,
    expose_debug: bool = False,
    expires_at: datetime | None = None,
) -> IssuedKey:
    if len(pepper) < MIN_PEPPER_BYTES:
        raise ValueError(f"GW_KEY_PEPPER must be at least {MIN_PEPPER_BYTES} bytes")
    prefix = "".join(secrets.choice(ALPHABET) for _ in range(12))
    secret = secrets.token_urlsafe(32)  # 43 ký tự
    return IssuedKey(
        plaintext=f"sk-acme-{prefix}.{secret}",
        new=NewKey(
            prefix=prefix,
            secret_hmac=hmac_secret(secret.encode(), pepper),
            name=name,
            owner_type=owner_type,
            owner_ref=owner_ref,
            dept=dept,
            allowed_models=allowed_models,
            rpm=rpm,
            tpm=tpm,
            max_concurrency=max_concurrency,
            trust_end_user_token=trust_end_user_token,
            expose_debug=expose_debug,
            expires_at=expires_at,
        ),
    )
