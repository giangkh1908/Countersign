"""Canonical JSON và `intent_sha256` (docs/design/approval.md §2.1).

Khoá sắp xếp, không khoảng trắng, UTF-8 không escape, chuẩn hoá NFC, từ chối float/NaN.
Dùng chung: approval-signer (ký intent), tickets-mcp (băm intent), audit.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def _prep(obj: Any) -> Any:
    if isinstance(obj, float):
        raise ValueError("float not allowed in canonical json")
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        return {unicodedata.normalize("NFC", str(k)): _prep(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_prep(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> bytes:
    return json.dumps(
        _prep(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def intent_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()
