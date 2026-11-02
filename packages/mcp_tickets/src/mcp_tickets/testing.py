"""`Fake<Port>` của tickets-mcp cho test nghiệp vụ (contracts §9.1 mục 9). Kế thừa port tường minh."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from acme_common.ports import Clock, Principal

from .ports import (
    AppliedOp,
    Approval,
    Audience,
    Comment,
    DuplicateIntent,
    Intent,
    RepositoryRolledBack,
    RepositoryUnavailable,
    Ticket,
    TicketConflict,
    TicketRepository,
    UnsupportedOperation,
)
from .ports.types import parse_iso


@dataclass(slots=True)
class FakeEvent:
    event_id: int
    ticket_code: str
    actor_sub: str
    action: str
    approval_jti: str
    intent_id: str
    intent_sha256: str
    before: dict[str, Any]
    after: dict[str, Any]


class FakeTicketRepository(TicketRepository):
    """Bộ nhớ, KHÔNG có RLS: chứng minh `TicketPolicy` ở service tự đủ an toàn."""

    def __init__(self, clock: Clock, tickets: Sequence[Ticket] = ()) -> None:
        self.clock = clock
        self.tickets: dict[str, Ticket] = {t.code: t for t in tickets}
        self._comments: dict[str, list[Comment]] = {}
        self.events: list[FakeEvent] = []
        self.audit: list[dict[str, Any]] = []
        self.fail_commit_with: Exception | None = None  # test chèn lỗi

    # --- helper cho test ---
    def add(self, t: Ticket) -> None:
        self.tickets[t.code] = t

    def touch(self, code: str, **changes: Any) -> None:
        """Giả lập người khác sửa ticket: đổi `updated_at` (và các trường khác)."""
        t = self.tickets[code]
        changes.setdefault("updated_at", t.updated_at + timedelta(seconds=1))
        self.tickets[code] = replace(t, **changes)

    def add_comment(self, code: str, c: Comment) -> None:
        self._comments.setdefault(code, []).append(c)

    # --- port ---
    async def get(self, code: str, principal: Principal) -> Ticket | None:
        return self.tickets.get(code)

    async def read_for_intent(self, code: str, principal: Principal) -> Ticket | None:
        return self.tickets.get(code)

    async def comments(self, code: str, principal: Principal, limit: int) -> list[Comment]:
        return list(self._comments.get(code, []))[-limit:]

    async def list_for(
        self,
        principal: Principal,
        relation: str,
        statuses: Sequence[str],
        limit: int,
        cursor: str | None,
    ) -> list[Ticket]:
        def mine(t: Ticket) -> bool:
            req, asg = t.requester_sub == principal.sub, t.assignee_sub == principal.sub
            return {"requested": req, "assigned": asg, "both": req or asg}[relation]

        rows = sorted(self.tickets.values(), key=lambda t: t.code, reverse=True)
        if cursor:
            rows = [t for t in rows if t.code < cursor]
        rows = [t for t in rows if mine(t) and (not statuses or t.status in statuses)]
        return [replace(t, cursor=t.code) for t in rows[:limit]]

    async def search(
        self,
        principal: Principal,
        query: str,
        scope: str,
        statuses: Sequence[str],
        priorities: Sequence[str],
        limit: int,
    ) -> list[Ticket]:
        words = query.lower().split()
        out = []
        for t in self.tickets.values():
            text = f"{t.title} {t.description}".lower()
            if not any(w in text for w in words):
                continue
            if scope == "mine" and principal.sub not in (t.requester_sub, t.assignee_sub):
                continue
            if statuses and t.status not in statuses:
                continue
            if priorities and t.priority not in priorities:
                continue
            out.append(t)
        return out[:limit]

    async def ticket_audience(self, draft: Mapping[str, Any]) -> Audience:
        depts = {d for d in (draft.get("requester_dept"), draft.get("assignee_dept")) if d}
        return Audience(int(draft.get("classification", 1)), frozenset(depts))

    async def commit_write(
        self, intent: Intent, approval: Approval, principal: Principal
    ) -> AppliedOp:
        if self.fail_commit_with is not None:
            raise self.fail_commit_with
        if intent.op not in ("close_ticket", "create_ticket"):
            raise UnsupportedOperation(intent.op)
        if any(
            e.intent_id == intent.intent_id or e.approval_jti == approval.jti for e in self.events
        ):
            raise DuplicateIntent
        if intent.op == "create_ticket":
            return self._create(intent, approval, principal)
        t = self.tickets.get(intent.ticket_code or "")
        if t is None or intent.expected_updated_at is None:
            raise RepositoryRolledBack
        if t.updated_at != parse_iso(intent.expected_updated_at) or t.status == "closed":
            raise TicketConflict
        now = self.clock.now()
        new = replace(
            t,
            status="closed",
            closed_at=now,
            closed_by=principal.sub,
            resolution=intent.args["resolution"],
            updated_at=now,
        )
        self.tickets[t.code] = new
        ev = FakeEvent(
            len(self.events) + 1, t.code, principal.sub, "close", approval.jti,
            intent.intent_id, intent.sha256, intent.before, intent.after,
        )  # fmt: skip
        self.events.append(ev)
        self.audit.append({"intent_id": intent.intent_id, "ticket_code": t.code})
        return AppliedOp("close_ticket", t.code, ev.event_id, approval.jti, new)

    def _create(self, intent: Intent, approval: Approval, principal: Principal) -> AppliedOp:
        a, now = intent.args, self.clock.now()
        code = f"TCK-{len(self.tickets) + 1000:06d}"  # cấp lúc commit
        new = Ticket(
            code=code, title=a["title"], description=a["body"], status="open",
            priority=a["priority"], category=a["category"], requester_sub=principal.sub,
            requester_dept=principal.dept[0], assignee_dept=a["assignee_dept"],
            classification=a["classification"], created_at=now, updated_at=now,
        )  # fmt: skip
        self.tickets[code] = new
        ev = FakeEvent(
            len(self.events) + 1, code, principal.sub, "create", approval.jti,
            intent.intent_id, intent.sha256, intent.before, intent.after,
        )  # fmt: skip
        self.events.append(ev)
        self.audit.append({"intent_id": intent.intent_id, "ticket_code": code})
        return AppliedOp("create_ticket", code, ev.event_id, approval.jti, new)

    async def find_applied(self, intent_id: str, principal: Principal) -> AppliedOp | None:
        for e in self.events:
            if e.intent_id == intent_id:
                op = "create_ticket" if e.action == "create" else "close_ticket"
                return AppliedOp(
                    op, e.ticket_code, e.event_id, e.approval_jti, self.tickets[e.ticket_code]
                )
        return None


class UnavailableTicketRepository(FakeTicketRepository):
    """Mọi lời gọi đọc đều lỗi hạ tầng (test fail-closed)."""

    async def get(self, code: str, principal: Principal) -> Ticket | None:
        raise RepositoryUnavailable("down")


def make_ticket(
    code: str = "TCK-000123",
    *,
    requester_sub: str = "u-req",
    assignee_sub: str | None = "u-agent",
    assignee_dept: str = "SALES",
    requester_dept: str = "SALES",
    status: str = "in_progress",
    classification: int = 1,
    updated_at: datetime | None = None,
    title: str = "Máy in tầng 3 không in được",
) -> Ticket:
    ts = updated_at or datetime(2025, 12, 31, 8, 12, 44, 123456, tzinfo=UTC)
    return Ticket(
        code=code,
        title=title,
        description="Mô tả",
        status=status,
        priority="medium",
        category="hardware",
        requester_sub=requester_sub,
        requester_dept=requester_dept,
        assignee_sub=assignee_sub,
        assignee_dept=assignee_dept,
        classification=classification,
        created_at=ts - timedelta(days=1),
        updated_at=ts,
    )
