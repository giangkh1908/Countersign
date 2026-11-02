"""Agent `report`: một AgentSpec + một dòng registry; `unverified_claims` do node kiểm chứng đặt, không do mô hình."""

from __future__ import annotations

from agent.agents.report import load_report_spec
from agent.availability import resolve_enabled_agents
from agent.factory import build_agent_registry
from agent.settings import Settings
from agent.testing import (
    FakeServiceProbe,
    FakeSupportJudge,
    FakeToolProvider,
    build_test_container,
    route,
    tool_call,
)
from langchain_core.messages import AIMessage

SEARCH = {
    "results": [
        {
            "chunk_id": 11,
            "doc_id": "d1",
            "text": "Doanh thu quy tang 5 phan tram so voi quy truoc.",
            "title": "Bao cao quy",
            "heading": "H",
            "source": "d1#2",
            "classification": "internal",
            "content": "<UNTRUSTED>noi dung</UNTRUSTED>",
        }
    ]
}
PREPARED = {
    "ok": True,
    "intent_id": "int-9",
    "intent_jws": "jws.opaque.value",
    "expires_at": "2099-01-01T00:00:00Z",
    "risk_flags": [],
    "op": "send_group_report",
}
GOOD = "Doanh thu quý tăng 5% [#11]."


def spec_calls(provider: FakeToolProvider):
    return [a for n, a in provider.calls if n == "prepare_send_group_report"]


def scripts(text: str, **extra):
    return {
        "router": [route("report")],
        "agent": [
            tool_call("search_documents", {"query": "doanh thu"}, "c1"),
            tool_call(
                "prepare_send_group_report", {"channel": "dept-eng", "text": text, **extra}, "c2"
            ),
        ],
    }


def make_provider() -> FakeToolProvider:
    return FakeToolProvider(
        {
            "search_documents": SEARCH,
            "list_report_channels": {"channels": []},
            "prepare_send_group_report": PREPARED,
        }
    )


# ---------------------------------------------------------------- spec / registry
def test_spec_is_declarative_and_least_privilege() -> None:
    s = load_report_spec(Settings(acme_env="test"))
    assert (s.route, s.node_name) == ("report", "report_agent")
    assert s.prepare_tools == {"prepare_send_group_report"}
    assert s.allowed_tool_names() == {
        "prepare_send_group_report",
        "search_documents",
        "get_document",
        "list_report_channels",
    }
    acc = s.access()
    assert (
        acc.prepare
        and acc.prepare.audience == "notify-mcp"
        and acc.prepare.scopes == ("notify:write",)
    )
    assert acc.commit and acc.commit.tools == frozenset({"commit_intent"})
    assert {r.audience for r in acc.read} == {"docs-mcp", "notify-mcp"}
    assert s.editable_fields == {"send_group_report": frozenset({"text"})}  # chỉ sửa được nội dung
    assert acc.prepare.cache_token is False


def test_registry_has_report_and_server_urls() -> None:
    s = Settings(acme_env="test")
    assert "report" in build_agent_registry(s).routes()
    assert s.mcp_servers["notify-mcp"].endswith(":8103/mcp")
    assert "notify-mcp" not in Settings(acme_env="test", mcp_notify_url="").mcp_servers


async def test_report_agent_off_when_notify_down_or_empty() -> None:
    url = "http://notify-mcp:8103/mcp"
    on = await resolve_enabled_agents(Settings(acme_env="test"), FakeServiceProbe({url}))
    assert "report" in on.enabled_agents
    off = await resolve_enabled_agents(Settings(acme_env="test"), FakeServiceProbe())
    assert "report" not in off.enabled_agents
    empty = FakeServiceProbe({url})
    s = await resolve_enabled_agents(Settings(acme_env="test", mcp_notify_url=""), empty)
    assert "report" not in s.enabled_agents and url not in empty.calls


# ---------------------------------------------------------------- unverified_claims
async def run_report(make_env, text: str, judge=None, **extra):
    provider = make_provider()
    env = make_env(provider, scripts(text, **extra))
    if judge is not None:
        env.c.judge_factory = lambda gw_token, run_id: judge
    tid = await env.new_thread()
    events = await env.run(tid, "Gui bao cao doanh thu vao nhom")
    return env, provider, tid, events


async def test_verified_text_is_not_flagged(make_env) -> None:
    _, provider, _, events = await run_report(make_env, GOOD)
    (args,) = spec_calls(provider)
    assert args["unverified_claims"] is False and args["text"] == GOOD
    assert any(e == "interrupt" for e, _ in events)


async def test_uncited_or_unsupported_text_is_flagged(make_env) -> None:
    _, provider, _, _ = await run_report(make_env, GOOD + " Lợi nhuận gấp đôi năm ngoái.")
    assert spec_calls(provider)[0]["unverified_claims"] is True
    _, provider, _, _ = await run_report(
        make_env, GOOD, judge=FakeSupportJudge(default="unsupported")
    )
    assert spec_calls(provider)[0]["unverified_claims"] is True


async def test_invalid_citation_code_is_flagged(make_env) -> None:
    _, provider, _, _ = await run_report(make_env, "Doanh thu quý tăng 5% [#999].")
    assert spec_calls(provider)[0]["unverified_claims"] is True


async def test_judge_failure_is_flagged_fail_closed(make_env) -> None:
    _, provider, _, _ = await run_report(make_env, GOOD, judge=FakeSupportJudge(fail=True))
    assert spec_calls(provider)[0]["unverified_claims"] is True


async def test_verification_off_is_flagged(make_env) -> None:
    provider = make_provider()
    env = make_env(provider, scripts(GOOD))
    env.c.settings = env.c.settings.model_copy(update={"agent_verify_citations": "off"})
    tid = await env.new_thread()
    await env.run(tid, "Gui bao cao")
    assert spec_calls(provider)[0]["unverified_claims"] is True


async def test_model_cannot_clear_the_flag(make_env) -> None:
    _, provider, _, _ = await run_report(make_env, "Câu không nguồn.", unverified_claims=False)
    assert spec_calls(provider)[0]["unverified_claims"] is True


async def test_edit_reverifies_the_new_text(make_env) -> None:
    env, provider, tid, events = await run_report(make_env, GOOD)
    iv = next(d for e, d in events if e == "interrupt")
    assert spec_calls(provider)[0]["unverified_claims"] is False
    await env.resume(
        tid,
        iv["interrupt_id"],
        {"type": "edit", "edits": {"text": "Chữ do người dùng tự viết, không có nguồn."}},
    )
    again = spec_calls(provider)
    assert len(again) == 2 and again[1]["unverified_claims"] is True
    assert again[1]["text"].startswith("Chữ do người dùng")
    assert again[1]["channel"] == "dept-eng"  # kênh không sửa được


async def test_edit_cannot_change_channel(make_env) -> None:
    env, provider, tid, events = await run_report(make_env, GOOD)
    iv = next(d for e, d in events if e == "interrupt")
    await env.resume(
        tid,
        iv["interrupt_id"],
        {"type": "edit", "edits": {"channel": "company-all", "text": GOOD}},
    )
    assert all(a["channel"] == "dept-eng" for a in spec_calls(provider))


async def test_approve_commits_through_notify(make_env) -> None:
    env, provider, tid, events = await run_report(make_env, GOOD)
    iv = next(d for e, d in events if e == "interrupt")
    assert iv["payload"]["op"] == "send_group_report" if "payload" in iv else True
    await env.resume(tid, iv["interrupt_id"], {"type": "approve", "approval_token": "tok-1"})
    assert provider.commits == [
        {"agent": "report_agent", "intent_id": "int-9", "approval_token": "tok-1"}
    ]


def test_build_test_container_still_works() -> None:
    assert build_test_container(FakeToolProvider(), {}).registry.routes()
    assert AIMessage  # import dùng cho kiểu của scripts
