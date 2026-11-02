"""Kiểu trung lập ở biên các port của tickets-mcp (kiểu intent dùng chung nằm ở acme_common.ports) (không phụ thuộc vendor)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


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
class AppliedOp:
    op: str
    ticket_code: str
    event_id: int
    approval_jti: str | None = None
    ticket: Ticket | None = None
    comment: Comment | None = None
