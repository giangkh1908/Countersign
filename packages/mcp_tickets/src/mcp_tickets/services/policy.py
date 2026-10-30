"""Chính sách thuần Python (02 §6.0): đủ an toàn kể cả khi repository KHÔNG có RLS. Không import adapter."""

from __future__ import annotations

from acme_common.ports import Principal
from acme_common.services.taint import TaintView

from ..ports import Audience, Ticket

LEADS = frozenset({"team_lead", "dept_manager"})
RISK_FLAGS = ("destructive", "internal_comment", "priority_urgent", "possible_downgrade")
# state machine (02 §6.3b); `closed` là trạng thái cuối
TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "resolved", "closed"}),
    "in_progress": frozenset({"open", "resolved", "closed"}),
    "resolved": frozenset({"in_progress", "closed"}),
    "closed": frozenset(),
}


def can_view(p: Principal, t: Ticket) -> bool:
    return (
        t.requester_sub == p.sub
        or (t.assignee_dept in p.dept and "employee" in p.roles)
        or "admin" in p.roles
    )


def can_modify(p: Principal, t: Ticket) -> bool:
    return (
        t.assignee_sub == p.sub
        or "admin" in p.roles
        or (t.assignee_dept in p.dept and bool(LEADS & set(p.roles)))
    )


def can_see_internal(p: Principal, t: Ticket) -> bool:
    return t.assignee_dept in p.dept and "employee" in p.roles


def can_close(t: Ticket) -> bool:
    return "closed" in TRANSITIONS.get(t.status, frozenset())


def taint_flags(taint: TaintView | None, aud: Audience) -> list[str]:
    """D17: `possible_downgrade` khi `max_class > aud.min_clearance` HOẶC
    (`aud.dept_set` không là tập con của `taint.dept_set` VÀ `max_class >= 1`). Xét thread lẫn recent.
    `taint is None` (Redis lỗi) => `taint_unknown`."""
    if taint is None:
        return ["taint_unknown"]
    for state in (taint.thread, taint.recent):
        if state.max_class > aud.min_clearance or (
            state.max_class >= 1 and not aud.dept_set <= state.dept_set
        ):
            return ["possible_downgrade"]
    return []


def taint_reasons(taint: TaintView, aud: Audience) -> dict[str, object]:
    """Nguồn (`thread`/`recent`) + số liệu; KHÔNG chứa nội dung."""
    for name in ("thread", "recent"):
        s = getattr(taint, name)
        if s.max_class > aud.min_clearance or (s.max_class >= 1 and not aud.dept_set <= s.dept_set):
            return {
                "reason": "possible_downgrade",
                "reason_source": name,
                "max_class": s.max_class,
                "dept_set": sorted(s.dept_set),
            }
    return {"reason": "possible_downgrade"}
