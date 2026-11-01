"""Kiểu dữ liệu trung lập ở biên các port của approval-signer (không import vendor)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from acme_common.ports import NotConfigured

# code -> HTTP status (contracts §4)
STATUS_BY_CODE: dict[str, int] = {
    "unauthorized": 401,
    "forbidden": 403,
    "intent_expired": 410,
    "intent_mismatch": 422,
    "intent_unrenderable": 422,
    "invalid_argument": 422,
    "rate_limited": 429,
    "upstream_unavailable": 503,
}


class SignerError(Exception):
    """Lỗi nghiệp vụ của signer. `code` thuộc contracts §4; `details` chỉ chứa mã/đường dẫn trường
    lấy từ payload đã ký, không chứa token, claim hay khoá."""

    def __init__(self, code: str, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.details = details

    @property
    def http_status(self) -> int:
        return STATUS_BY_CODE.get(self.code, 500)


class IntentVerifierNotConfigured(NotConfigured):
    pass


class ApprovalSignerNotConfigured(NotConfigured):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedIntent:
    """Payload intent đã qua kiểm chữ ký/iss/aud/sub/exp, cùng `intent_sha256` do signer tự tính."""

    payload: dict[str, Any]
    sha256: str

    @property
    def intent_id(self) -> str:
        return str(self.payload["intent_id"])

    @property
    def sub(self) -> str:
        return str(self.payload["sub"])

    @property
    def iss(self) -> str:
        return str(self.payload["iss"])


@dataclass(frozen=True, slots=True)
class RenderModel:
    """Render model (docs/design/approval.md §2.1). `display` là phần SPA render, đã escape ký tự nguy hiểm."""

    intent_id: str
    op: str
    target: dict[str, Any]
    before: dict[str, Any]
    after: dict[str, Any]
    risk_flags: list[str]
    expires_at: str
    intent_sha256: str
    server_time: str
    display: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "op": self.op,
            "target": self.target,
            "before": self.before,
            "after": self.after,
            "risk_flags": self.risk_flags,
            "expires_at": self.expires_at,
            "intent_sha256": self.intent_sha256,
            "server_time": self.server_time,
            "display": self.display,
        }


@dataclass(frozen=True, slots=True)
class ApprovalToken:
    token: str = field(repr=False)
    jti: str
    expires_at: datetime
