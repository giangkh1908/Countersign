"""CSRF double-submit có ràng buộc phiên: header == cookie == HMAC(k_csrf, sid)."""

from __future__ import annotations

import hmac

from .crypto import Crypto


def csrf_valid(crypto: Crypto, *, sid: str, header: str | None, cookie: str | None) -> bool:
    if not header or not cookie:
        return False
    expected = crypto.csrf_for(sid)
    return hmac.compare_digest(header.encode(), cookie.encode()) and hmac.compare_digest(
        header.encode(), expected.encode()
    )
