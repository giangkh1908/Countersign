from __future__ import annotations

import pytest
from agent.testing import AUTH, PREPARED, FakeToolProvider, route, tool_call
from langchain_core.messages import AIMessage

SEARCH = {
    "results": [
        {
            "doc_id": "d1",
            "title": "Quy trinh nghi phep",
            "heading": "H",
            "source": "d1#2",
            "classification": "internal",
            "content": "<UNTRUSTED>noi dung</UNTRUSTED>",
        }
    ]
}


def names(events):
    return [e for e, _ in events]


def terminal(events):
    return [e for e in names(events) if e in ("done", "error")]


def ticket_scripts():
    return {
        "router": [route("ticket")],
        "agent": [
            tool_call("prepare_close_ticket", {"code": "TCK-000123", "resolution": "da xu ly xong"})
        ],
    }


async def start_ticket(make_env, **provider_kw):
    provider = FakeToolProvider({"prepare_close_ticket": PREPARED}, **provider_kw)
    env = make_env(provider, ticket_scripts())
    tid = await env.new_thread()
    events = await env.run(tid, "Dong ticket TCK-000123")
    iv = next(d for e, d in events if e == "interrupt")
    return env, provider, tid, events, iv


async def test_docs_question_with_citations(make_env):
    provider = FakeToolProvider({"search_documents": SEARCH})
    env = make_env(
        provider,
        {
            "router": [route("docs")],
            "agent": [
                tool_call("search_documents", {"query": "nghi phep"}),
                AIMessage("Xin nghi phep qua HR."),
            ],
        },
    )
    tid = await env.new_thread()
    events = await env.run(tid, "Quy trinh nghi phep?")
    assert names(events)[0] == "run_start"
    assert (
        "route" in names(events) and "tool_start" in names(events) and "tool_end" in names(events)
    )
    cit = next(d for e, d in events if e == "citations")
    assert cit["items"][0]["doc_id"] == "d1"
    text = "".join(d["text"] for e, d in events if e == "token")
    assert "nghi phep" in text
    assert terminal(events) == ["done"]
    assert names(events)[-1] == "done"
    assert provider.tool_threads == [tid]


async def test_approve_commits_with_token_and_clears_it(make_env):
    env, provider, tid, events, iv = await start_ticket(make_env)
    p = iv["payload"]
    assert set(["intent_id", "op", "expires_at", "intent_jws"]) <= set(p)
    assert p["intent_id"] == "int-1" and p["op"] == "close_ticket"
    assert terminal(events) == ["done"] and events[-1][1]["status"] == "interrupted"
    assert provider.commits == []
    ev2 = await env.resume(
        tid, iv["interrupt_id"], {"type": "approve", "approval_token": "tok-123"}
    )
    assert provider.commits == [
        {"agent": "ticket_agent", "intent_id": "int-1", "approval_token": "tok-123"}
    ]
    assert terminal(ev2) == ["done"] and ev2[-1][1]["status"] == "completed"
    snap = await env.c.graph.aget_state({"configurable": {"thread_id": tid}})
    assert snap.values["approval"]["approval_token"] is None


async def test_reject_does_not_commit(make_env):
    env, provider, tid, _, iv = await start_ticket(make_env)
    ev2 = await env.resume(tid, iv["interrupt_id"], {"type": "reject"})
    assert provider.commits == []
    assert terminal(ev2) == ["done"] and ev2[-1][1]["status"] == "rejected"


@pytest.mark.parametrize("code", ["intent_expired", "conflict"])
async def test_commit_failure_ends_with_single_error(make_env, code):
    res = {"ok": False, "error": {"code": code, "message": "m", "details": {}}}
    env, provider, tid, _, iv = await start_ticket(make_env, commit_result=res)
    ev2 = await env.resume(tid, iv["interrupt_id"], {"type": "approve", "approval_token": "t"})
    assert terminal(ev2) == ["error"] and ev2[-1][1]["code"] == code
    assert any(e == "token" for e in names(ev2))
    assert len(provider.commits) == 1


async def test_resume_wrong_interrupt_id_is_409(make_env):
    env, _, tid, _, _ = await start_ticket(make_env)
    r = await env.client.post(
        f"/v1/threads/{tid}/resume",
        json={"interrupt_id": "int_other", "decision": {"type": "reject"}},
        headers=AUTH,
    )
    assert r.status_code == 409


async def test_run_blocked_while_interrupt_pending(make_env):
    env, _, tid, _, _ = await start_ticket(make_env)
    r = await env.client.post(
        f"/v1/threads/{tid}/runs",
        json={"input": {"text": "x"}, "client_msg_id": "m2"},
        headers=AUTH,
    )
    assert r.status_code == 409


async def test_auth_rejections(make_env):
    env = make_env(FakeToolProvider(), {})
    r = await env.client.post("/v1/threads", json={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    r = await env.client.post("/v1/threads", json={}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    # token hợp lệ nhưng sai aud (không có agent-service): từ chối (403 theo contracts §2)
    from dataclasses import replace

    from agent.testing import make_principal

    env.c.verifier.add("other", replace(make_principal(), audience=("llm-gateway",)))
    r = await env.client.post("/v1/threads", json={}, headers={"Authorization": "Bearer other"})
    assert r.status_code == 403
    assert env.c.verifier.calls[-1] == ("other", "agent-service")


async def test_thread_ownership(make_env):
    env = make_env(FakeToolProvider(), {})
    tid = await env.new_thread()
    env.c.verifier.add("t2", __import__("agent.testing", fromlist=["x"]).make_principal("u2"))
    r = await env.client.get(f"/v1/threads/{tid}/messages", headers={"Authorization": "Bearer t2"})
    assert r.status_code == 404


async def test_chitchat_direct_answer_single_done(make_env):
    env = make_env(
        FakeToolProvider(), {"router": [route("chitchat")], "direct": [AIMessage("Xin chao ban")]}
    )
    tid = await env.new_thread()
    events = await env.run(tid, "chao")
    assert terminal(events) == ["done"]
    msgs = (await env.client.get(f"/v1/threads/{tid}/messages", headers=AUTH)).json()
    assert [m["role"] for m in msgs["messages"]] == ["user", "assistant"]
    assert msgs["pending_interrupt"] is None


async def test_unexpected_exception_yields_single_error(make_env):
    env = make_env(FakeToolProvider(), {"router": []})  # hết kịch bản => AssertionError
    tid = await env.new_thread()
    events = await env.run(tid, "x")
    assert terminal(events) == ["error"] and events[-1][1]["code"] == "internal"
