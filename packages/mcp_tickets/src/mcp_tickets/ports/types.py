"""Kiểu trung lập ở biên các port của tickets-mcp (không phụ thuộc vendor)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

IntentStatus = Literal["pending", "committing", "committed", "failed"]
CasStatus = Literal["owned", "committing", "committed", "failed", "missing"]


def iso_micro(dt: datetime) -> str:
    """ISO-8601 UTC với 6 chữ số thập phân: so sánh chính xác với cột `timestamptz`."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Ticket:
    code: str
    title: str
    description: str
    status: str
    priority: str
    category: str
    requester_sub: str
    requester_dept: str
    assignee_dept: str
    created_at: datetime
    updated_at: datetime
    assignee_sub: str | None = None
    classification: int = 1
    closed_at: datetime | None = None
    closed_by: str | None = None
    resolution: str | None = None
    cursor: str | None = None  # mờ đục, do adapter đặt khi liệt kê


@dataclass(frozen=True, slots=True)
class Comment:
    id: int
    author_sub: str
    body: str
    internal: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Audience:
    """Đối tượng sẽ thấy bản ghi đích: `ticket_audience(draft)`."""

    min_clearance: int
    dept_set: frozenset[str]


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
    ticket_code: str | None


@dataclass(frozen=True, slots=True)
class AppliedOp:
    op: str
    ticket_code: str
    event_id: int
    approval_jti: str | None = None
    ticket: Ticket | None = None
    comment: Comment | None = None
