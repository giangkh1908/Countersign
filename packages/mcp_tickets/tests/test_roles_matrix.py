"""Ma trận quyền ở MCP server: mọi ô role x thao tác, cho phép và từ chối, ở cả prepare lẫn commit.

Từ chối thì không ghi gì: không có intent trong Redis, không đổi ticket, không có ticket_events.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp_tickets.testing import FakeTicketRepository, make_ticket
from tickets_harness import INTENT_PREFIX, Env, principal

ME = "u-me"
COLLEAGUE = "u-colleague"
CLOSE = {"code": "TCK-000500", "resolution": "Đã xử lý xong theo yêu cầu."}
CREATE = {
    "title": "Máy chiếu phòng họp 2 không lên hình",
    "body": "Đã thử đổi cáp HDMI nhưng vẫn không có tín hiệu.",
    "category": "other",
    "assignee_dept": "HR",
}

# Tập vai trò thực tế của seed (employee đi kèm) và các tổ hợp có vai trò chặn.
# (tạo ticket, đóng ticket được giao, đóng ticket trong phòng) theo bảng §1.
CASES: dict[str, tuple[tuple[str, ...], tuple[bool, bool, bool]]] = {
    "employee": (("employee",), (True, True, False)),
    "team_lead": (("employee", "team_lead"), (True, True, False)),
    "dept_manager": (("employee", "dept_manager"), (True, True, True)),
    "management": (("management",), (True, True, True)),
    "admin": (("employee", "admin"), (False, False, False)),
    "admin_alone": (("admin",), (False, False, False)),
    "auditor": (("auditor",), (False, False, False)),
    "auditor_with_employee": (("employee", "auditor"), (False, False, False)),
    "management_and_admin": (("management", "admin"), (False, False, False)),
    "dept_manager_and_auditor": (("employee", "dept_manager", "auditor"), (False, False, False)),
    "no_roles": ((), (False, False, False)),
    "unknown_role": (("requester",), (False, False, False)),
}


def make_env() -> Env:
    env = Env()
    env.repo = FakeTicketRepository(env.clock, [])
    env.service.repo = env.repo
    env.repo.add(make_ticket("TCK-000500", assignee_sub=ME, requester_sub="u-req"))
    env.repo.add(make_ticket("TCK-000501", assignee_sub=COLLEAGUE, requester_sub="u-req"))
    return env


async def intent_keys(env: Env) -> list[Any]:
    return await env.redis.keys(INTENT_PREFIX + "*")


def snapshot(env: Env) -> tuple[Any, ...]:
    return (dict(env.repo.tickets), list(env.repo.events), list(env.repo.audit))


async def commit(env: Env, out: dict[str, Any], who: Any) -> tuple[bool, dict[str, Any]]:
    token, _ = env.approval(out, sub=who.sub)
    return await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}, who
    )


@pytest.mark.parametrize("name", sorted(CASES))
async def test_create_ticket_cell(name: str) -> None:
    roles, (can_create, _, _) = CASES[name]
    env = make_env()
    who = principal(ME, roles=roles)
    before = snapshot(env)
    err, out = await env.call("prepare_create_ticket", CREATE, who)
    if not can_create:
        assert err and out["code"] == "forbidden"
        assert await intent_keys(env) == []  # từ chối prepare thì không tốn intent
        assert snapshot(env) == before
        return
    assert not err, out
    err, res = await commit(env, out, who)
    assert not err, res
    assert res["ticket"]["requester_sub"] == ME and res["ticket"]["status"] == "open"
    assert len(env.repo.events) == 1 and env.repo.events[0].action == "create"


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("scenario", ["assigned", "in_dept"])
async def test_close_ticket_cell(name: str, scenario: str) -> None:
    roles, (_, can_assigned, can_dept) = CASES[name]
    allowed = can_assigned if scenario == "assigned" else can_dept
    code = "TCK-000500" if scenario == "assigned" else "TCK-000501"
    env = make_env()
    who = principal(ME, roles=roles)
    before = snapshot(env)
    err, out = await env.call("prepare_close_ticket", {**CLOSE, "code": code}, who)
    if not allowed:
        assert err and out["code"] in ("forbidden", "not_found")
        assert await intent_keys(env) == []
        assert snapshot(env) == before
        return
    assert not err, out
    err, res = await commit(env, out, who)
    assert not err, res
    assert env.repo.tickets[code].status == "closed"
    assert env.repo.tickets[code].closed_by == ME


@pytest.mark.parametrize("name", sorted(CASES))
async def test_close_ticket_in_other_dept_is_never_allowed(name: str) -> None:
    roles, _ = CASES[name]
    env = make_env()
    env.repo.add(make_ticket("TCK-000502", assignee_sub=COLLEAGUE, assignee_dept="HR",
                             requester_dept="HR", requester_sub="u-req"))  # fmt: skip
    before = snapshot(env)
    err, out = await env.call(
        "prepare_close_ticket",
        {**CLOSE, "code": "TCK-000502"},
        principal(ME, dept=("SALES",), roles=roles),
    )
    admin_sees = "admin" in roles  # admin xem được nhưng không ghi
    assert err and out["code"] == ("forbidden" if admin_sees else "not_found")
    assert snapshot(env) == before


# ---- vai trò đổi giữa prepare và commit: commit phân quyền lại, từ chối thì không ghi, không đốt jti
@pytest.mark.parametrize("revoked", [("employee", "admin"), ("employee", "auditor"), ("auditor",)])
async def test_commit_close_rechecks_matrix(revoked: tuple[str, ...]) -> None:
    env = make_env()
    out_err, out = await env.call(
        "prepare_close_ticket", CLOSE, principal(ME, roles=("employee", "team_lead"))
    )
    assert not out_err, out
    before = snapshot(env)
    now_who = principal(ME, roles=revoked)
    token, jti = env.approval(out, sub=ME)
    err, res = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}, now_who
    )
    assert err and res["code"] in ("forbidden", "not_found")
    assert snapshot(env) == before
    assert await env.replay.consume(jti, 180)  # từ chối đoán trước được: jti chưa bị đốt


@pytest.mark.parametrize("revoked", [("employee", "admin"), ("auditor",), ("requester",)])
async def test_commit_create_rechecks_matrix(revoked: tuple[str, ...]) -> None:
    env = make_env()
    err, out = await env.call("prepare_create_ticket", CREATE, principal(ME, roles=("employee",)))
    assert not err, out
    before = snapshot(env)
    token, jti = env.approval(out, sub=ME)
    err, res = await env.call(
        "commit_intent",
        {"intent_id": out["intent_id"], "approval_token": token},
        principal(ME, roles=revoked),
    )
    assert err and res["code"] == "forbidden"
    assert snapshot(env) == before
    assert await env.replay.consume(jti, 180)


def test_policy_view_rights_unchanged_for_admin_and_management() -> None:
    from mcp_tickets.services import policy

    t = make_ticket("TCK-000600", assignee_sub=COLLEAGUE, requester_sub="u-req")
    assert policy.can_view(principal("x", roles=("employee", "admin")), t)
    assert policy.can_view(principal("x", roles=("management",)), t)  # sửa lệch số 3
    assert not policy.can_view(principal("x", roles=("auditor",)), t)
    assert not policy.can_view(principal("x", dept=("HR",), roles=("management",)), t)
