"""Ma trận quyền (docs/design/actions-roles.md §1): mọi ô, cả cho phép lẫn từ chối."""

from __future__ import annotations

import pytest
from acme_common.services.capabilities import ROLE_CAPS, Capability, allows

C = Capability
# Bảng viết tay từ tài liệu, KHÔNG sinh từ ROLE_CAPS để test bắt được lệch.
EXPECTED: dict[str, set[Capability]] = {
    "employee": {C.CREATE_TICKET, C.CLOSE_ASSIGNED},
    "team_lead": {C.CREATE_TICKET, C.CLOSE_ASSIGNED, C.REPORT_DEPT},
    "dept_manager": {C.CREATE_TICKET, C.CLOSE_ASSIGNED, C.CLOSE_IN_DEPT, C.REPORT_DEPT},
    "management": {
        C.CREATE_TICKET,
        C.CLOSE_ASSIGNED,
        C.CLOSE_IN_DEPT,
        C.REPORT_DEPT,
        C.REPORT_COMPANY,
    },
    "admin": set(),
    "auditor": set(),
}


@pytest.mark.parametrize("cap", list(Capability))
@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_every_cell(role: str, cap: Capability) -> None:
    assert allows([role], cap) is (cap in EXPECTED[role])


@pytest.mark.parametrize("cap", list(Capability))
@pytest.mark.parametrize("blocker", ["admin", "auditor"])
@pytest.mark.parametrize("other", ["employee", "team_lead", "dept_manager", "management"])
def test_blocking_roles_win_over_any_other_role(blocker: str, other: str, cap: Capability) -> None:
    assert allows([other, blocker], cap) is False
    assert allows([blocker, other], cap) is False


@pytest.mark.parametrize("cap", list(Capability))
def test_unknown_or_empty_roles_have_nothing(cap: Capability) -> None:
    assert allows([], cap) is False
    assert allows(["requester", "guest"], cap) is False


def test_roles_accumulate_when_not_blocked() -> None:
    assert allows(["employee", "team_lead"], C.REPORT_DEPT)
    assert not allows(["employee", "team_lead"], C.REPORT_COMPANY)


def test_table_matches_expected() -> None:
    assert {r: set(c) for r, c in ROLE_CAPS.items()} == {r: c for r, c in EXPECTED.items() if c}
