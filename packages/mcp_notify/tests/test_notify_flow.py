"""Luồng notify-mcp: quyền theo ma trận, taint fail-closed, gửi tối đa một lần, các nhánh lỗi kênh."""

from __future__ import annotations

import hashlib

import jwt
import pytest
from acme_common.services.canonical import canonical_json
from mcp_notify.ports import ChannelSendError, DeliveryLogUnavailable, DeliveryRecord
from notify_harness import LEAD, Env, principal

TEXT = "Báo cáo tuần: doanh thu tăng."  # trùng mặc định của harness.prepare


@pytest.fixture
def env() -> Env:
    return Env()


def eng_lead(**kw):
    return principal(roles=("employee", "team_lead"), dept=("ENG",), **kw)


# ---------------------------------------------------------------- ma trận quyền x kênh
CASES = [
    # (vai trò, phòng, kênh, được gửi)
    (("employee",), ("ENG",), "dept-eng", False),
    (("team_lead",), ("ENG",), "dept-eng", True),
    (("team_lead",), ("ENG",), "dept-sales", False),  # phòng khác
    (("team_lead",), ("ENG",), "company-all", False),
    (("dept_manager",), ("ENG",), "dept-eng", True),
    (("dept_manager",), ("ENG",), "company-all", False),
    (("management",), ("ENG",), "dept-eng", True),
    (("management",), ("ENG",), "dept-sales", True),  # REPORT_COMPANY gửi mọi kênh
    (("management",), ("ENG",), "company-all", True),
    (("admin",), ("ENG",), "dept-eng", False),
    (("auditor",), ("ENG",), "company-all", False),
    (("employee", "admin"), ("ENG",), "dept-eng", False),
    (("team_lead", "admin"), ("ENG",), "dept-eng", False),  # admin là vai trò chặn
    (("management", "auditor"), ("ENG",), "company-all", False),
    (("stranger",), ("ENG",), "dept-eng", False),
]


@pytest.mark.parametrize(("roles", "dept", "channel", "ok"), CASES)
async def test_matrix_prepare_and_commit(env: Env, roles, dept, channel, ok) -> None:
    who = principal(roles=roles, dept=dept)
    err, out = await env.call("prepare_send_group_report", {"channel": channel, "text": TEXT}, who)
    if not ok:
        assert err and out["code"] == "forbidden"
        return
    assert not err, out
    err, res, _ = await env.commit(out, who)
    assert not err, res
    assert env.sender.sent[-1].chat_ref == CHANNELS_REF[channel]


CHANNELS_REF = {
    "dept-eng": "TG_CHAT_ENG",
    "dept-sales": "TG_CHAT_SALES",
    "company-all": "TG_CHAT_ALL",
}


@pytest.mark.parametrize(("roles", "dept", "channel", "ok"), CASES)
async def test_list_channels_follows_matrix(env: Env, roles, dept, channel, ok) -> None:
    err, res = await env.call("list_report_channels", {}, principal(roles=roles, dept=dept))
    assert not err
    names = {c["channel"] for c in res["channels"]}
    assert (channel in names) is ok
    assert "chat" not in str(res).lower() or "TG_CHAT" not in str(res)  # không lộ chat_ref/ID


async def test_unknown_channel_not_found(env: Env) -> None:
    err, res = await env.call(
        "prepare_send_group_report", {"channel": "khong-co", "text": TEXT}, eng_lead()
    )
    assert err and res["code"] == "not_found"


async def test_role_change_between_prepare_and_commit(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    demoted = principal(roles=("employee",), dept=("ENG",))
    err, res, _ = await env.commit(out, demoted)
    assert err and res["code"] == "forbidden"
    assert env.sender.calls == 0 and not env.deliveries.rows


# ---------------------------------------------------------------- prepare
async def test_prepare_signs_intent_without_sending(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    p = jwt.decode(
        out["intent_jws"],
        env.intent_key.public_key(),
        algorithms=["ES256"],
        options={"verify_exp": False, "verify_aud": False},
    )
    assert p["iss"] == "notify-mcp" and p["op"] == "send_group_report" and p["sub"] == LEAD
    assert (
        p["target"] == {"channel": "dept-eng"}
        and p["before"] == {}
        and p["after"] == {"text": TEXT}
    )
    assert p["args_canonical"] == canonical_json({"channel": "dept-eng", "text": TEXT}).decode()
    assert out["risk_flags"] == [] and env.sender.calls == 0 and not env.deliveries.rows


@pytest.mark.parametrize(
    "text",
    ["Xem https://evil.example/x?d=1", "vào www.evil.test", "gửi về evil.com ngay", "t.me/abc"],
)
async def test_url_flag(env: Env, text: str) -> None:
    out = await env.prepare(text=text, who=eng_lead())
    assert out["risk_flags"] == ["contains_url"]


async def test_unverified_claims_flag_not_signed_as_arg(env: Env) -> None:
    out = await env.prepare(unverified_claims=True, who=eng_lead())
    assert out["risk_flags"] == ["unverified_claims"]
    p = jwt.decode(out["intent_jws"], options={"verify_signature": False})
    assert "unverified" not in p["args_canonical"] and "unverified_claims" in p["risk_flags"]


async def test_both_flags_raise_risk(env: Env) -> None:
    out = await env.prepare(text="xem http://a.b/c", unverified_claims=True, who=eng_lead())
    assert out["risk_flags"] == ["contains_url", "unverified_claims"]
    p = jwt.decode(out["intent_jws"], options={"verify_signature": False})
    assert p["risk"] == "high"


@pytest.mark.parametrize("text", ["", "   ", "a" * 3501, "xin chào\x00", "mã\x1b[31m độc"])
async def test_invalid_text(env: Env, text: str) -> None:
    err, res = await env.call(
        "prepare_send_group_report", {"channel": "dept-eng", "text": text}, eng_lead()
    )
    assert err and res["code"] == "invalid_argument"


async def test_max_length_accepted(env: Env) -> None:
    out = await env.prepare(text="a" * 3500, who=eng_lead())
    assert out["ok"]


async def test_scope_required(env: Env) -> None:
    err, res = await env.call(
        "list_report_channels", {}, principal(scopes=("docs:read",), roles=("team_lead",))
    )
    assert err and res["code"] in ("forbidden", "unauthorized")


# ---------------------------------------------------------------- commit
async def test_commit_sends_exact_signed_text_once(env: Env) -> None:
    decomposed = "Café báo cáo: tổng kết quý"  # NFD; chuỗi ký là NFC
    out = await env.prepare(text=decomposed, who=eng_lead())
    signed = jwt.decode(out["intent_jws"], options={"verify_signature": False})
    import json

    signed_text = json.loads(signed["args_canonical"])["text"]
    err, res, _ = await env.commit(out, eng_lead())
    assert not err, res
    assert res["delivery"] == "sent" and res["channel"] == "dept-eng"
    assert env.sender.sent[0].text == signed_text  # byte-by-byte
    assert res["text_sha256"] == hashlib.sha256(signed_text.encode()).hexdigest()
    row = env.deliveries.rows[out["intent_id"]]
    assert row.status == "sent" and row.text_sha256 == res["text_sha256"]
    assert signed_text not in repr(row)  # sổ không lưu nội dung


async def test_commit_twice_sends_once(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    err, _, _ = await env.commit(out, eng_lead())
    assert not err
    err, res, _ = await env.commit(out, eng_lead())  # approval khác jti
    assert err and res["code"] == "approval_replayed"
    assert res["details"]["delivery"] == "sent"
    assert env.sender.calls == 1


async def test_replay_same_approval(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    token, _ = env.approval(out)
    args = {"intent_id": out["intent_id"], "approval_token": token}
    assert not (await env.call("commit_intent", args, eng_lead()))[0]
    err, res = await env.call("commit_intent", args, eng_lead())
    assert err and res["code"] == "approval_replayed" and env.sender.calls == 1


async def test_delivery_row_exists_blocks_send_even_if_redis_lost_state(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    env.deliveries.rows[out["intent_id"]] = DeliveryRecord(
        out["intent_id"], "dept-eng", "0" * 64, "sending"
    )
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "approval_replayed" and env.sender.calls == 0


async def test_wrong_audience_approval_rejected(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    token, _ = env.approval(out, aud="tickets-mcp")
    err, res = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}, eng_lead()
    )
    assert err and res["code"] == "approval_invalid" and env.sender.calls == 0


async def test_args_must_match(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    token, _ = env.approval(out)
    err, res = await env.call(
        "commit_intent",
        {
            "intent_id": out["intent_id"],
            "approval_token": token,
            "args": {"channel": "company-all", "text": TEXT},
        },
        eng_lead(),
    )
    assert err and res["code"] == "intent_mismatch" and env.sender.calls == 0


# ---------------------------------------------------------------- taint (fail-closed)
async def test_taint_within_limit_allowed(env: Env) -> None:
    await env.taint(LEAD, 1)
    out = await env.prepare(who=eng_lead())  # dept-eng có max_class 1
    err, _, _ = await env.commit(out, eng_lead())
    assert not err


@pytest.mark.parametrize("thread", ["T1", None])
async def test_taint_above_channel_denied_at_prepare(env: Env, thread) -> None:
    await env.taint(LEAD, 2, thread="T1" if thread else None)
    err, res = await env.call(
        "prepare_send_group_report",
        {"channel": "dept-eng", "text": TEXT},
        eng_lead(),
        thread_id=thread,
    )
    assert err and res["code"] == "forbidden"
    assert res["details"]["reason"] == "taint_exceeds_channel"
    assert res["details"]["channel_max_class"] == 1


async def test_recent_taint_from_other_thread_counts(env: Env) -> None:
    await env.taint(LEAD, 2, thread="OTHER")  # ghi cả :recent
    err, res = await env.call(
        "prepare_send_group_report", {"channel": "dept-eng", "text": TEXT}, eng_lead(), "T1"
    )
    assert err and res["details"]["reason_source"] == "recent"


async def test_company_channel_max_class_zero(env: Env) -> None:
    await env.taint(LEAD, 1)
    who = principal(roles=("management",))
    err, res = await env.call(
        "prepare_send_group_report", {"channel": "company-all", "text": TEXT}, who
    )
    assert err and res["code"] == "forbidden"


async def test_taint_rechecked_at_commit(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    await env.taint(LEAD, 2)  # giữa hai bước, thread đọc thêm tài liệu mật
    err, res, _ = await env.commit(out, eng_lead())
    assert (
        err and res["code"] == "forbidden" and res["details"]["reason"] == "taint_exceeds_channel"
    )
    assert env.sender.calls == 0 and not env.deliveries.rows


async def test_taint_none_denied_at_prepare_and_commit(env: Env, monkeypatch) -> None:
    out = await env.prepare(who=eng_lead())

    async def boom(*a, **k):
        from redis.exceptions import ConnectionError as RedisConnError

        raise RedisConnError("down")

    monkeypatch.setattr(env.redis, "hgetall", boom)
    err, res = await env.call(
        "prepare_send_group_report", {"channel": "dept-eng", "text": TEXT}, eng_lead()
    )
    assert err and res["code"] == "forbidden" and res["details"]["reason"] == "taint_unknown"
    err, res, _ = await env.commit(out, eng_lead())
    # Redis hỏng thì intent cũng không nạp được: vẫn bị từ chối, không gửi
    assert err and res["code"] in ("forbidden", "upstream_unavailable")
    assert env.sender.calls == 0


async def test_taint_none_denied_at_commit_authorize(env: Env, monkeypatch) -> None:
    from mcp_notify.services import report_service

    out = await env.prepare(who=eng_lead())

    async def none_taint(*a, **k):
        return None

    monkeypatch.setattr(report_service, "get_taint", none_taint)
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "forbidden" and res["details"]["reason"] == "taint_unknown"
    assert env.sender.calls == 0 and not env.deliveries.rows


# ---------------------------------------------------------------- lỗi kênh
async def test_definitely_not_sent_marks_failed_and_rolls_back(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    env.sender.fail_with = ChannelSendError("http_4xx", status=403, delivered="no")
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "upstream_unavailable"
    assert res["details"]["reason"] == "retry_prepare"
    assert env.deliveries.rows[out["intent_id"]].status == "failed"
    assert env.sender.sent == []
    # intent đã `failed`: phải prepare lại, không dùng lại intent này
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "intent_mismatch"


async def test_unknown_outcome_never_resends(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    env.sender.fail_after_send = ChannelSendError("timeout")
    err, res, _ = await env.commit(out, eng_lead())
    assert not err
    assert res["delivery"] == "unknown" and "kiểm tra" in res["notice"]
    assert env.deliveries.rows[out["intent_id"]].status == "unknown"
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "approval_replayed" and res["details"]["delivery"] == "unknown"
    assert env.sender.calls == 1


async def test_log_unreachable_before_write_is_rolled_back(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    env.deliveries.fail_begin = DeliveryLogUnavailable("connect", not_written=True)
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "upstream_unavailable" and env.sender.calls == 0


async def test_log_write_outcome_unknown_does_not_send(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    env.deliveries.fail_begin = DeliveryLogUnavailable("insert")
    err, res, _ = await env.commit(out, eng_lead())
    assert err and res["code"] == "upstream_unavailable" and env.sender.calls == 0


async def test_finish_failure_still_reports_sent(env: Env) -> None:
    out = await env.prepare(who=eng_lead())
    env.deliveries.fail_finish = True
    err, res, _ = await env.commit(out, eng_lead())
    assert not err and res["delivery"] == "sent"
    assert (
        env.deliveries.rows[out["intent_id"]].status == "sending"
    )  # tra cứu sau coi là "không chắc"


async def test_audit_has_no_message_text(env: Env) -> None:
    out = await env.prepare(text="bí mật nội bộ XYZ123", who=eng_lead())
    await env.commit(out, eng_lead())
    assert "XYZ123" not in repr(
        env.sink.records if hasattr(env.sink, "records") else env.sink.__dict__
    )
