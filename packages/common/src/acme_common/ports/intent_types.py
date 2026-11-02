"""Kiểu trung lập của hạ tầng intent + phê duyệt (docs/design/approval.md), dùng chung cho mọi MCP ghi.

Không phụ thuộc vendor. Nghiệp vụ riêng của từng MCP (ticket, notify) nằm ở package của MCP đó.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

IntentStatus = Literal["pending", "committing", "committed", "failed"]
CasStatus = Literal["owned", "committing", "committed", "failed", "missing"]


@dataclass(frozen=True, slots=True)
class Draft:
    """Bản nháp đã tính ở `prepare_*`; `IntentIssuer` ký nguyên văn."""

    target: dict[str, Any]
    before: dict[str, Any]
    after: dict[str, Any]
    expected_updated_at: str | None
    risk_flags: tuple[str, ...] = ()
    risk: str | None = None


@dataclass(frozen=True, slots=True)
class SignedIntent:
    intent_id: str
    jws: str
    sha256: str
    exp: int  # epoch giây
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredIntent:
    """Intent đọc lại từ kho; `payload` đã verify chữ ký và băm lại khớp `sha256`."""

    intent_id: str
    jws: str
    sha256: str
    sub: str
    status: IntentStatus
    owner_jti: str | None
    updated_at: float  # epoch giây
    payload: dict[str, Any]

    @property
    def exp(self) -> int:
        return int(self.payload["exp"])


@dataclass(frozen=True, slots=True)
class CasResult:
    status: CasStatus
    owner_jti: str | None = None
    updated_at: float = 0.0


@dataclass(frozen=True, slots=True)
class Approval:
    jti: str
    intent_id: str
    intent_sha256: str


@dataclass(frozen=True, slots=True)
class Intent:
    """Thao tác đã duyệt, dựng từ payload JWS đã verify (KHÔNG từ agent)."""

    intent_id: str
    op: str
    sha256: str
    sub: str
    args: dict[str, Any]
    before: dict[str, Any]
    after: dict[str, Any]
    expected_updated_at: str | None
    target: dict[str, Any] = field(default_factory=dict)

    @property
    def ticket_code(self) -> str | None:
        code = self.target.get("ticket_code")
        return code if isinstance(code, str) else None
