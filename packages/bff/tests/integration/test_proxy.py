"""Proxy SSE/REST tới agent + signer, luồng phê duyệt, ánh xạ lỗi."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from bff_harness import (
    APPROVAL_TOKEN,
    INTENT_JWS,
    MSG_ID,
    SHA,
    THREAD,
    Env,
    interrupt_frame,
    sse,
)

CHAT = {"text": "Đóng ticket TCK-1", "client_msg_id": MSG_ID}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        ev = next(line[7:] for line in block.split("\n") if line.startswith("event: "))
        data = next(line[6:] for line in block.split("\n") if line.startswith("data: "))
        out.append((ev, json.loads(data)))
    return out


def set_interrupt_stream(
    env: Env, interrupt_id: str = "int_1", intent_id: str = "intent-1"
) -> None:
    env.backends.agent_body = sse(
        ("run_start", {"run_id": "r", "thread_id": THREAD, "request_ids": []}),
        interrupt_frame(interrupt_id, intent_id),
        ("done", {"status": "interrupted", "message_id": "m"}),
    )


async def test_chat_streams_via_agent_service_audience(logged_in: Env) -> None:
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no" and r.headers["cache-control"] == "no-store"
    assert [e for e, _ in parse_sse(r.text)] == ["run_start", "token", "done"]
    # chỉ một exchange, đúng một audience
    assert logged_in.broker.calls == [("user-1", "agent-service", ("agent:invoke",))]
    run = [c for c in logged_in.backends.calls if c[2].endswith("/runs")][0]
    assert run[3] == {"input": {"text": CHAT["text"]}, "client_msg_id": MSG_ID}


async def test_chat_without_thread_creates_one_and_emits_thread_event_first(logged_in: Env) -> None:
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": None})
    events = parse_sse(r.text)
    assert events[0] == ("thread", {"thread_id": THREAD, "title": "Đóng ticket TCK-1"})
    assert events[-1][0] == "done"
    assert logged_in.backends.paths("agent.test")[:2] == [
        "/v1/threads",
        f"/v1/threads/{THREAD}/runs",
    ]


async def test_agent_token_is_cached_per_session(logged_in: Env) -> None:
    for _ in range(3):
        await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    assert len(logged_in.broker.calls) == 1


async def test_interrupt_is_registered_and_jws_stripped(logged_in: Env) -> None:
    set_interrupt_stream(logged_in)
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    ev = dict(parse_sse(r.text))
    assert ev["interrupt"] == {
        "interrupt_id": "int_1",
        "intent_id": "intent-1",
        "op": "close_ticket",
        "expires_at": "2026-01-01T00:05:00Z",
    }
    assert INTENT_JWS not in r.text
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    pend = json.loads(await logged_in.redis.hget(f"bff:sess:{sid}:pend", "int_1"))
    assert pend["intent_jws"] == INTENT_JWS and pend["state"] == "seen"


async def test_approval_flow_uses_signer_audience_and_agent_audience_separately(
    logged_in: Env,
) -> None:
    set_interrupt_stream(logged_in)
    b = logged_in.browser
    await b.post("/api/chat", json={**CHAT, "thread_id": THREAD})

    v = await b.post("/api/intents/verify", json={"thread_id": THREAD, "interrupt_id": "int_1"})
    assert v.status_code == 200
    logged_in.backends.agent_body = sse(("done", {"status": "completed", "message_id": "m"}))
    card = v.json()
    assert card["intent_sha256"] == SHA and card["title"] == "Đóng ticket TCK-1"
    assert card["display_fields"][0]["kind"] == "ticket_ref" and card["op"] == "close_ticket"
    assert "intent_jws" not in card

    a = await b.post(
        "/api/approvals", json={"thread_id": THREAD, "interrupt_id": "int_1", "intent_sha256": SHA}
    )
    assert a.status_code == 200
    events = parse_sse(a.text)
    assert events[0] == ("approval", {"expires_at": "2026-01-01T00:02:00Z"})
    assert APPROVAL_TOKEN not in a.text

    aud = [c[1] for c in logged_in.broker.calls]
    assert aud == ["agent-service", "approval-signer"]  # mỗi lần một audience, không gộp
    assert logged_in.broker.calls[1][2] == ("signer:approve",)
    resume = [c for c in logged_in.backends.calls if c[2].endswith("/resume")][0]
    assert resume[3]["decision"] == {"type": "approve", "approval_token": APPROVAL_TOKEN}
    assert resume[3]["interrupt_id"] == "int_1"
    signer_paths = logged_in.backends.paths("signer.test")
    assert signer_paths == ["/v1/intents/verify", "/v1/approvals"]
    signer_calls = [c for c in logged_in.backends.calls if c[0] == "signer.test"]
    assert all(c[3] == {"intent_jws": INTENT_JWS} for c in signer_calls)

    # tokens trong phiên được mã hoá, mỗi slot riêng
    sid = b.client.cookies.get("__Host-sid")
    raw = await logged_in.redis.hgetall(f"bff:sess:{sid}")
    assert raw["agent_enc"] and raw["signer_token"] and "fake:" not in "".join(raw.values())
    # pend đã xoá sau khi resume bắt đầu → bấm lại là không còn interrupt
    again = await b.post(
        "/api/approvals", json={"thread_id": THREAD, "interrupt_id": "int_1", "intent_sha256": SHA}
    )
    assert again.status_code == 404 and again.json()["error"]["code"] == "interrupt_not_found"


async def test_approve_requires_verify_first_and_matching_sha(logged_in: Env) -> None:
    set_interrupt_stream(logged_in)
    b = logged_in.browser
    await b.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    body = {"thread_id": THREAD, "interrupt_id": "int_1", "intent_sha256": SHA}
    r = await b.post("/api/approvals", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "intent_mismatch"  # chưa verify
    await b.post("/api/intents/verify", json={"thread_id": THREAD, "interrupt_id": "int_1"})
    r = await b.post("/api/approvals", json={**body, "intent_sha256": "b" * 64})
    assert (
        r.status_code == 422 and r.json()["error"]["code"] == "intent_mismatch"
    )  # lệch thẻ đã hiển thị
    assert "/v1/approvals" not in logged_in.backends.paths("signer.test")


async def test_verify_unknown_or_foreign_interrupt_is_404(logged_in: Env) -> None:
    r = await logged_in.browser.post(
        "/api/intents/verify", json={"thread_id": THREAD, "interrupt_id": "int_x"}
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "interrupt_not_found"
    assert logged_in.backends.paths("signer.test") == []


async def test_signer_errors_are_mapped(logged_in: Env) -> None:
    set_interrupt_stream(logged_in)
    b = logged_in.browser
    await b.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    body = {"thread_id": THREAD, "interrupt_id": "int_1"}
    for status, code, want_status, want_code in [
        (422, "intent_unrenderable", 422, "intent_unrenderable"),
        (422, "intent_mismatch", 422, "intent_mismatch"),
        (403, "forbidden", 403, "forbidden"),
        (500, "internal", 502, "upstream_unavailable"),
        (429, "rate_limited", 429, "rate_limited"),
        (410, "intent_expired", 410, "intent_expired"),
    ]:
        logged_in.backends.signer_error = (status, code)
        r = await b.post("/api/intents/verify", json=body)
        assert (r.status_code, r.json()["error"]["code"]) == (want_status, want_code), (
            status,
            code,
        )
    # 410 đánh dấu intent chết → các lần sau 410 mà không gọi signer nữa
    n = len(logged_in.backends.paths("signer.test"))
    r = await b.post("/api/intents/verify", json=body)
    assert r.status_code == 410 and len(logged_in.backends.paths("signer.test")) == n


async def test_signer_absent_returns_503_upstream_unavailable_and_bff_stays_healthy(
    logged_in: Env,
) -> None:
    set_interrupt_stream(logged_in)
    b = logged_in.browser
    await b.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    logged_in.backends.signer_down = True
    body = {"thread_id": THREAD, "interrupt_id": "int_1"}
    r = await b.post("/api/intents/verify", json=body)
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"
    assert r.json()["error"]["retryable"] is True
    r = await b.post("/api/approvals", json={**body, "intent_sha256": SHA})
    assert r.status_code in (422, 503)  # chưa verify thì 422; không bao giờ 500
    assert (await b.get("/healthz")).status_code == 200


async def test_token_exchange_denied_maps_to_502_per_contract() -> None:
    from bff_harness import build_env

    e = await build_env(deny=("agent-service",))
    try:
        await e.browser.login(e.idp)
        r = await e.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
        assert r.status_code == 502
        err = r.json()["error"]
        assert err == {
            "code": "upstream_unavailable",
            "message": err["message"],
            "retryable": True,
            "request_id": r.headers["x-request-id"],
        }
        assert "agent-service" not in r.text and "invalid_scope" not in r.text
        assert e.backends.paths("agent.test") == []  # không gọi agent khi chưa có token
    finally:
        await e.browser.client.aclose()
        await e.container.aclose()


async def test_agent_http_errors_are_mapped(logged_in: Env) -> None:
    for status, want in [(409, (409, "conflict")), (404, (404, "not_found"))]:
        logged_in.backends.agent_status = status
        r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
        assert (r.status_code, r.json()["error"]["code"]) == want
    # slot SSE được nhả sau lỗi
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    assert int(await logged_in.redis.get(f"bff:sess:{sid}:rl:streams") or 0) == 0


async def test_agent_401_retries_exchange_once_then_session_expired(logged_in: Env) -> None:
    # token agent bị agent từ chối ⇒ exchange lại 1 lần; vẫn 401 ⇒ session_expired
    logged_in.backends.agent_status = 401
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"
    assert [c[1] for c in logged_in.broker.calls] == ["agent-service", "agent-service"]


async def test_threads_messages_cost_delete(logged_in: Env) -> None:
    b = logged_in.browser
    lst = await b.get("/api/threads?limit=20")
    assert lst.status_code == 200 and lst.json()["items"][0]["thread_id"] == THREAD
    assert lst.json()["next_before"] is None

    msgs = await b.get(f"/api/threads/{THREAD}/messages")
    body = msgs.json()
    assert body["pending_interrupt"]["interrupt_id"] == "int_1" and "intent_jws" not in msgs.text
    assert body["cost"] == {"thread_usd": 0.1} and body["messages"][0]["role"] == "user"
    # pending_interrupt từ messages cũng vào pend để verify được
    v = await b.post("/api/intents/verify", json={"thread_id": THREAD, "interrupt_id": "int_1"})
    assert v.status_code == 200

    cost = await b.get("/api/requests/r1")
    assert cost.json() == {
        "request_id": "r1",
        "cost_usd": 0.01,
        "alias": "acme-fast",
        "tokens_in": 1,
        "tokens_out": 2,
        "cache": "miss",
    }
    assert (await b.delete(f"/api/threads/{THREAD}")).status_code == 204
    assert (await b.get("/api/requests/bad%20id")).status_code in (400, 404)


async def test_reload_of_messages_does_not_burn_card_budget(logged_in: Env) -> None:
    for _ in range(15):
        r = await logged_in.browser.get(f"/api/threads/{THREAD}/messages")
        assert r.json()["pending_interrupt"] is not None


async def test_reject_blocks_same_intent_for_a_while(logged_in: Env) -> None:
    set_interrupt_stream(logged_in)
    b = logged_in.browser
    await b.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    r = await b.post(
        "/api/resume",
        json={
            "thread_id": THREAD,
            "interrupt_id": "int_1",
            "decision": {"type": "reject", "reason": "no"},
        },
    )
    assert r.status_code == 200
    resume = [c for c in logged_in.backends.calls if c[2].endswith("/resume")][0]
    assert resume[3]["decision"] == {"type": "reject", "reason": "no"}
    # agent trình lại cùng intent_id (interrupt id mới) → bị chặn
    set_interrupt_stream(logged_in, interrupt_id="int_2")
    again = await b.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    events = parse_sse(again.text)
    assert events[-1][0] == "error"
    assert (
        events[-1][1]["code"] == "conflict"
        and events[-1][1]["reason"] == "intent_rejected_recently"
    )
    assert "interrupt" not in [e for e, _ in events]


async def test_cards_per_thread_hour_cap() -> None:
    from bff_harness import build_env, make_settings

    e = await build_env(make_settings(bff_max_cards_per_thread_hour=1))
    try:
        await e.browser.login(e.idp)
        set_interrupt_stream(e, "int_1", "i1")
        await e.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
        set_interrupt_stream(e, "int_2", "i2")
        r = await e.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
        last = parse_sse(r.text)[-1]
        assert last[0] == "error" and last[1]["code"] == "rate_limited"
        assert last[1]["reason"] == "cards_per_thread_hour"
    finally:
        await e.browser.client.aclose()
        await e.container.aclose()


async def test_stream_slots_limit_and_release(logged_in: Env) -> None:
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    await logged_in.redis.set(f"bff:sess:{sid}:rl:streams", 3, ex=300)
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


async def test_upstream_without_terminal_event_gets_error_frame(logged_in: Env) -> None:
    logged_in.backends.agent_body = sse(("token", {"text": "dở dang", "node": "n"}))
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    events = parse_sse(r.text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "upstream_unavailable"
    assert events[-1][1]["retryable"] is True


async def test_unknown_agent_events_are_dropped_and_others_forwarded_verbatim(
    logged_in: Env,
) -> None:
    payload = {"items": [{"doc_id": "d", "title": "T"}]}
    logged_in.backends.agent_body = sse(
        ("debug_internal", {"secret": "x"}),
        ("citations", payload),
        ("cost", {"turn_usd": 0.1, "thread_usd": 0.2, "calls": []}),
        ("done", {"status": "completed", "message_id": "m"}),
    )
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    events = parse_sse(r.text)
    assert [e for e, _ in events] == ["citations", "cost", "done"]
    assert events[0][1] == payload


async def test_extended_citations_payload_is_forwarded_verbatim(logged_in: Env) -> None:
    """R2 (rag-citations §5.4): BFF chuyển nguyên văn items/sentences/answer_status/verify."""
    payload = {
        "items": [
            {
                "n": 1,
                "doc_id": "d",
                "passage": "Đoạn",
                "char_start": 10,
                "evidence_start": 12,
                "evidence_end": 15,
                "verdict": "supported",
                "sentence_ids": [0],
            }
        ],
        "sentences": [{"id": 0, "start": 0, "end": 9, "cites": [1], "verdict": "supported"}],
        "answer_status": "answered",
        "verify": {"enabled": True, "pairs": 1, "judge_calls": 1, "ms": 5},
    }
    logged_in.backends.agent_body = sse(
        ("citations", payload), ("done", {"status": "completed", "message_id": "m"})
    )
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    assert parse_sse(r.text)[0] == ("citations", payload)


async def test_agent_sse_error_is_forwarded(logged_in: Env) -> None:
    logged_in.backends.agent_body = sse(
        ("error", {"code": "rate_limited", "message": "Quá tải", "retryable": True})
    )
    r = await logged_in.browser.post("/api/chat", json={**CHAT, "thread_id": THREAD})
    events = parse_sse(r.text)
    assert events == [("error", {"code": "rate_limited", "message": "Quá tải", "retryable": True})]


async def test_streaming_response_is_incremental_end_to_end(logged_in: Env) -> None:
    """Bytes tới ASGI client theo từng khung khi upstream chưa kết thúc."""
    import asyncio

    gate = asyncio.Event()
    released = asyncio.Event()

    async def upstream() -> AsyncIterator[bytes]:
        yield sse(("token", {"text": "một", "node": "n"}))
        released.set()
        await gate.wait()
        yield sse(("done", {"status": "completed", "message_id": "m"}))

    import httpx
    from bff_harness import _Stream

    class StreamingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=_Stream(upstream)
            )

    logged_in.container.agent._stream = httpx.AsyncClient(transport=StreamingTransport())
    scope_cookies = "; ".join(f"{k}={v}" for k, v in logged_in.browser.client.cookies.items())
    body = json.dumps({**CHAT, "thread_id": THREAD}).encode()
    sent: list[bytes] = []
    first = asyncio.Event()

    sent_body = False

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()  # trình duyệt vẫn mở kết nối

    async def send(msg):
        if msg["type"] == "http.response.body" and msg.get("body"):
            sent.append(msg["body"])
            first.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/chat",
        "raw_path": b"/api/chat",
        "query_string": b"",
        "root_path": "",
        "server": ("bff.test", 443),
        "client": ("1.2.3.4", 1),
        "headers": [
            (b"host", b"bff.test"),
            (b"origin", b"https://bff.test"),
            (b"cookie", scope_cookies.encode()),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-csrf-token", logged_in.browser.client.cookies.get("__Host-csrf").encode()),
        ],
    }
    task = asyncio.create_task(logged_in.app(scope, receive, send))
    await asyncio.wait_for(first.wait(), 5)
    assert not task.done(), "phản hồi phải đang mở khi upstream chưa xong"
    assert b"event: token" in sent[0] and b"event: done" not in b"".join(sent)
    gate.set()
    await asyncio.wait_for(task, 5)
    assert b"event: done" in b"".join(sent)
