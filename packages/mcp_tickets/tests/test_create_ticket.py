"""`prepare_create_ticket` đi đúng luồng intent + approval; không có đường ghi thứ hai.

Kèm hồi quy ký số, hết hạn, chống phát lại trên đường tạo ticket.
"""

from __future__ import annotations

from typing import Any

import jwt
import pytest
from acme_common.services.canonical import canonical_json
from mcp_tickets.testing import make_ticket
from tickets_harness import ASSIGNEE, INTENT_PREFIX, OTHER, Env, new_key, principal

CREATE = {
    "title": "Cần cấp tài khoản VPN cho nhân viên mới",
    "body": "Nhân viên bắt đầu làm việc từ thứ Hai tuần sau.",
    "category": "account_access",
    "priority": "high",
    "assignee_dept": "HR",
}
NORM = {**CREATE, "classification": 1}


@pytest.fixture
def env() -> Env:
    return Env()


async def prepare(env: Env, args: dict[str, Any] | None = None, who=None) -> dict[str, Any]:
    err, out = await env.call("prepare_create_ticket", args or CREATE, who)
    assert not err, out
    return out


async def commit(env: Env, out: dict[str, Any], **kw: Any) -> tuple[bool, dict[str, Any], str]:
    token, jti = env.approval(out, **kw)
    err, res = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}
    )
    return err, res, jti


async def test_prepare_signs_intent_without_writing(env: Env) -> None:
    out = await prepare(env)
    p = jwt.decode(
        out["intent_jws"],
        env.intent_key.public_key(),
        algorithms=["ES256"],
        options={"verify_exp": False, "verify_aud": False},
    )
    assert (
        p["op"] == "create_ticket"
        and p["sub"] == ASSIGNEE
        and p["target"] == {"title": CREATE["title"]}
    )
    assert p["args_canonical"] == canonical_json(NORM).decode()  # mặc định điền đủ và được ký
    assert p["before"] == {} and p["after"] == {**NORM, "status": "open"}
    assert "expected_updated_at" not in p and "code" not in p["args_canonical"]
    assert p["risk_flags"] == [] and p["risk"] == "low"  # chưa đọc gì: không có taint
    # prepare không tạo gì: chưa có ticket mới, chưa có event
    assert list(env.repo.tickets) == ["TCK-000123"] and env.repo.events == []
    assert await env.redis.hget(INTENT_PREFIX + out["intent_id"], "status") == "pending"


async def test_code_is_assigned_at_commit_and_intent_denial_spends_none(env: Env) -> None:
    out = await prepare(env)
    assert "ticket_code" not in out
    err, res, jti = await commit(env, out)
    assert not err, res
    assert res["op"] == "create_ticket" and res["approval_jti"] == jti
    code = res["ticket"]["code"]
    assert code in env.repo.tickets and code != "TCK-000123"
    t = env.repo.tickets[code]
    assert (t.status, t.requester_sub, t.requester_dept, t.assignee_dept) == (
        "open",
        ASSIGNEE,
        "SALES",
        "HR",
    )
    ev = env.repo.events[0]
    assert ev.action == "create" and ev.intent_id == out["intent_id"] and ev.approval_jti == jti
    # prepare bị từ chối không để lại intent
    keys_before = await env.redis.keys(INTENT_PREFIX + "*")
    err, _ = await env.call("prepare_create_ticket", CREATE, principal(roles=("auditor",)))
    assert err and await env.redis.keys(INTENT_PREFIX + "*") == keys_before


async def test_commit_twice_creates_one_ticket(env: Env) -> None:
    out = await prepare(env)
    token, _ = env.approval(out)
    args = {"intent_id": out["intent_id"], "approval_token": token}
    err, res = await env.call("commit_intent", args)
    assert not err
    n = len(env.repo.tickets)
    err, res = await env.call("commit_intent", args)
    assert err and res["code"] == "approval_replayed"
    assert res["details"]["already_applied"] is True
    # approval mới (jti khác) cho cùng intent cũng không tạo thêm
    err, res, _ = await commit(env, out)
    assert err and res["code"] == "approval_replayed"
    assert len(env.repo.tickets) == n and len(env.repo.events) == 1


async def test_args_tampered_after_approval_is_rejected(env: Env) -> None:
    out = await prepare(env)
    token, _ = env.approval(out)
    err, res = await env.call(
        "commit_intent",
        {
            "intent_id": out["intent_id"],
            "approval_token": token,
            "args": {**NORM, "title": "Tiêu đề khác với bản đã duyệt"},
        },
    )
    assert err and res["code"] == "intent_mismatch"
    assert len(env.repo.tickets) == 1


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"key": new_key()}, "approval_invalid"),  # khoá lạ
        ({"sha": "0" * 64}, "intent_mismatch"),
        ({"sub": OTHER}, "approval_mismatch"),
        ({"aud": "notify-mcp"}, "approval_invalid"),
    ],
)
async def test_bad_approvals_on_create(env: Env, kw: dict[str, Any], code: str) -> None:
    out = await prepare(env)
    token, _ = env.approval(out, **kw)
    err, res = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}
    )
    assert err and res["code"] == code
    assert len(env.repo.tickets) == 1 and env.repo.events == []


async def test_missing_or_garbage_approval_on_create(env: Env) -> None:
    out = await prepare(env)
    err, res = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": "x" * 20}
    )
    assert err and res["code"] == "approval_invalid"
    err, res = await env.call("commit_intent", {"intent_id": out["intent_id"]})
    assert err and res["code"] == "invalid_argument"
    assert len(env.repo.tickets) == 1


async def test_expired_approval_and_intent_on_create(env: Env) -> None:
    out = await prepare(env)
    ok_args = {"intent_id": out["intent_id"]}
    token, _ = env.approval(out)
    env.clock.advance(121)
    err, res = await env.call("commit_intent", {**ok_args, "approval_token": token})
    assert err and res["code"] == "approval_expired"
    env.clock.advance(400)
    token2, _ = env.approval(out)
    err, res = await env.call("commit_intent", {**ok_args, "approval_token": token2})
    assert err and res["code"] in ("intent_expired", "intent_not_found")
    assert len(env.repo.tickets) == 1 and env.repo.events == []


async def test_replayed_jti_on_create(env: Env) -> None:
    out = await prepare(env)
    out2 = await prepare(env)
    token, jti = env.approval(out)
    err, _ = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}
    )
    assert not err
    # dùng lại jti đã đốt cho intent khác
    token2, _ = env.approval(out2, jti=jti)
    err, res = await env.call(
        "commit_intent", {"intent_id": out2["intent_id"], "approval_token": token2}
    )
    assert err and res["code"] == "approval_replayed"
    assert len(env.repo.events) == 1


async def test_argument_validation(env: Env) -> None:
    for bad in [
        {**CREATE, "category": "unknown"},
        {**CREATE, "priority": "critical"},
        {**CREATE, "assignee_dept": "hr; drop"},
        {**CREATE, "classification": 9},
        {**CREATE, "extra": 1},
        {k: v for k, v in CREATE.items() if k != "title"},
        {**CREATE, "title": "x" * 201},
    ]:
        err, res = await env.call("prepare_create_ticket", bad)
        assert err and res["code"] == "invalid_argument", bad
    err, res = await env.call("prepare_create_ticket", CREATE, principal(scopes=("tickets:read",)))
    assert err and res["code"] == "forbidden"


async def test_classification_cannot_exceed_clearance(env: Env) -> None:
    err, res = await env.call("prepare_create_ticket", {**CREATE, "classification": 2})
    assert err and res["code"] == "forbidden"
    assert await env.redis.keys(INTENT_PREFIX + "*") == []


async def test_caller_without_department_is_denied(env: Env) -> None:
    err, res = await env.call("prepare_create_ticket", CREATE, principal(dept=()))
    assert err and res["code"] == "forbidden"


async def test_taint_flags_on_create(env: Env) -> None:
    env.repo.add(
        make_ticket(
            "TCK-000300",
            assignee_dept="HR",
            requester_dept="HR",
            classification=2,
            requester_sub=ASSIGNEE,
        )
    )
    err, _ = await env.call("get_ticket", {"code": "TCK-000300"}, thread_id="T9")
    assert not err
    err, out = await env.call("prepare_create_ticket", CREATE, thread_id="T9")
    assert not err and "possible_downgrade" in out["risk_flags"]
    p = jwt.decode(out["intent_jws"], options={"verify_signature": False})
    assert p["risk"] == "high"
    # chính sách block: từ chối, không có intent
    blocked = Env(taint_policy="block")
    blocked.repo.add(
        make_ticket("TCK-000300", assignee_dept="HR", requester_dept="HR", classification=2,
                    requester_sub=ASSIGNEE)
    )  # fmt: skip
    await blocked.call("get_ticket", {"code": "TCK-000300"}, thread_id="T9")
    err, res = await blocked.call("prepare_create_ticket", CREATE, thread_id="T9")
    assert err and res["code"] == "forbidden"
    assert await blocked.redis.keys(INTENT_PREFIX + "*") == []


async def test_urgent_priority_flag(env: Env) -> None:
    out = await prepare(env, {**CREATE, "priority": "urgent"})
    assert "priority_urgent" in out["risk_flags"]


async def test_no_second_write_path(env: Env) -> None:
    names = {t["name"] for t in env.host.tool_manifest()}
    assert not {n for n in names if n.startswith(("create_", "close_", "update_"))}
    # tool đọc không đổi dữ liệu dù gọi bằng quyền ghi
    n = len(env.repo.tickets)
    await env.call("list_my_tickets", {})
    assert len(env.repo.tickets) == n and env.repo.events == []
