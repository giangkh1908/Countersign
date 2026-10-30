"""Hash-chain HMAC cho `audit_log` / `tool_audit` (contracts §3.1, §3.6).

hash = HMAC-SHA256(key[hmac_kid], prev_hash || canonical(row)); `id` và `ts` do app gán TRƯỚC khi băm.
`canonical(row)` = canonical JSON (khoá sắp xếp, NFC, không float) của các cột nghiệp vụ + `hmac_kid`.
`intent_id` chỉ nằm trong hàm băm khi row có khoá đó (bảng `tool_audit`).
Hàm ở đây thuần (không I/O); ghi DB: `audit.pg`.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..services.canonical import canonical_json

GENESIS_HASH = bytes(32)
_HASHED_FIELDS = (
    "id",
    "ts",
    "request_id",
    "actor_type",
    "actor_id",
    "end_user_sub",
    "action",
    "resource",
    "decision",
    "details",
)


def _ts_str(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ValueError("audit ts must be timezone-aware")
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _norm(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in _HASHED_FIELDS:
        v = row.get(f)
        if f == "ts":
            v = _ts_str(v) if isinstance(v, datetime) else v
        elif f == "request_id" and v is not None:
            v = str(uuid.UUID(str(v)))
        elif f == "details" and v is None:
            v = {}
        out[f] = v
    if "intent_id" in row:
        iid = row["intent_id"]
        out["intent_id"] = None if iid is None else str(uuid.UUID(str(iid)))
    out["hmac_kid"] = int(row["hmac_kid"])
    return out


def canonical_row(row: Mapping[str, Any]) -> bytes:
    """Raise `ValueError` nếu `details` có float."""
    return canonical_json(_norm(row))


@dataclass(frozen=True, slots=True)
class AuditKeyring:
    """Khoá HMAC theo `hmac_kid` (xoay khoá: thêm kid mới, giữ kid cũ để verify)."""

    keys: Mapping[int, bytes]
    current_kid: int

    def __post_init__(self) -> None:
        if self.current_kid not in self.keys:
            raise ValueError("current_kid not in keys")

    def key(self, kid: int) -> bytes:
        try:
            return self.keys[kid]
        except KeyError:
            raise KeyError(f"unknown hmac_kid {kid}") from None

    @classmethod
    def single(cls, secret: str | bytes, kid: int = 1) -> AuditKeyring:
        raw = secret.encode() if isinstance(secret, str) else secret
        if len(raw) < 16:
            raise ValueError("AUDIT_HMAC_KEY too short (>= 16 bytes)")
        return cls({kid: raw}, kid)


def compute_hash(keyring: AuditKeyring, prev_hash: bytes, row: Mapping[str, Any]) -> bytes:
    key = keyring.key(int(row["hmac_kid"]))
    return hmac.new(key, prev_hash + canonical_row(row), hashlib.sha256).digest()


def seal(keyring: AuditKeyring, prev_hash: bytes, row: Mapping[str, Any]) -> dict[str, Any]:
    """Gán `hmac_kid` hiện tại, `prev_hash`, `hash` cho row (đã có `id`, `ts`)."""
    sealed = {**row, "hmac_kid": keyring.current_kid}
    sealed["prev_hash"] = prev_hash
    sealed["hash"] = compute_hash(keyring, prev_hash, sealed)
    return sealed


@dataclass(frozen=True, slots=True)
class VerifyResult:
    ok: bool
    checked: int
    bad_id: int | None = None
    reason: str | None = None  # hash_mismatch | chain_break | unknown_kid | tail_missing
    last_id: int | None = None
    last_hash: bytes | None = None


def verify_chain(
    rows: Iterable[Mapping[str, Any]],
    keyring: AuditKeyring,
    *,
    prev_hash: bytes = GENESIS_HASH,
    expected_tail: tuple[int, bytes] | None = None,
) -> VerifyResult:
    """Kiểm chuỗi theo thứ tự `id` tăng dần.

    - Sửa bản ghi => `hash_mismatch`; xoá giữa chuỗi / chèn => `chain_break` (prev_hash lệch).
    - Xoá phần đuôi chỉ phát hiện được khi có `expected_tail=(last_id, last_hash)` từ anchor
      (=> `tail_missing`). Bắt đầu từ anchor: truyền `prev_hash=anchor.last_hash` và các row sau đó.
    """
    checked = 0
    last_id: int | None = None
    last_hash = prev_hash
    tail_seen = expected_tail is None
    for row in rows:
        rid = int(row["id"])
        if bytes(row["prev_hash"]) != last_hash:
            return VerifyResult(False, checked, rid, "chain_break", last_id, last_hash)
        try:
            expect = compute_hash(keyring, last_hash, row)
        except KeyError:
            return VerifyResult(False, checked, rid, "unknown_kid", last_id, last_hash)
        if not hmac.compare_digest(expect, bytes(row["hash"])):
            return VerifyResult(False, checked, rid, "hash_mismatch", last_id, last_hash)
        checked += 1
        last_id, last_hash = rid, bytes(row["hash"])
        if expected_tail is not None and rid == expected_tail[0]:
            if last_hash != expected_tail[1]:
                return VerifyResult(False, checked, rid, "hash_mismatch", last_id, last_hash)
            tail_seen = True
    if not tail_seen:
        return VerifyResult(False, checked, None, "tail_missing", last_id, last_hash)
    return VerifyResult(True, checked, None, None, last_id, last_hash)
