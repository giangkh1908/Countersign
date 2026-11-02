"""Ma trận quyền vai trò x hành động (docs/design/actions-roles.md §1). Nguồn duy nhất phía Python.

Điều kiện RLS của `tickets` (infra/postgres/init/sql/30-tickets.sql) là bản viết tay tương đương;
test tham số hoá mọi ô để hai bản không lệch nhau.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Capability(StrEnum):
    CREATE_TICKET = "create_ticket"
    CLOSE_ASSIGNED = "close_assigned"
    CLOSE_IN_DEPT = "close_in_dept"
    REPORT_DEPT = "report_dept"
    REPORT_COMPANY = "report_company"


C = Capability
# Vai trò CHẶN: có mặt là mất mọi quyền ghi, bất kể vai trò khác (quyền không cộng dồn qua chúng).
WRITE_BLOCKING: frozenset[str] = frozenset({"admin", "auditor"})

ROLE_CAPS: dict[str, frozenset[Capability]] = {
    "employee": frozenset({C.CREATE_TICKET, C.CLOSE_ASSIGNED}),
    "team_lead": frozenset({C.CREATE_TICKET, C.CLOSE_ASSIGNED, C.REPORT_DEPT}),
    "dept_manager": frozenset({C.CREATE_TICKET, C.CLOSE_ASSIGNED, C.CLOSE_IN_DEPT, C.REPORT_DEPT}),
    "management": frozenset(
        {C.CREATE_TICKET, C.CLOSE_ASSIGNED, C.CLOSE_IN_DEPT, C.REPORT_DEPT, C.REPORT_COMPANY}
    ),
}


def allows(roles: Iterable[str], cap: Capability) -> bool:
    """Vai trò không biết thì không có quyền gì; vai trò chặn thắng mọi vai trò khác."""
    rs = set(roles)
    if rs & WRITE_BLOCKING:
        return False
    return any(cap in ROLE_CAPS.get(r, frozenset()) for r in rs)
