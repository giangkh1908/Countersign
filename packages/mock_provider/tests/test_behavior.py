"""Lỗi chaos, seed tái lập, auth, /__control, /metrics."""

import json

import httpx
import pytest
from mock_provider.main import create_app

from .conftest import CONTROL_TOKEN, METRICS_TOKEN, make_settings

OAI = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
ANT = {"model": "m", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}
GEM = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
ROUTES = [
    ("/v1/chat/completions", OAI),
    ("/v1/messages", ANT),
    ("/v1beta/models/g:generateContent", GEM),
]


@pytest.mark.parametrize(("path", "body"), ROUTES)
@pytest.mark.parametrize(
    ("kind", "status"), [("429", 429), ("500", 500), ("503", 503), ("timeout", 504)]
)
async def test_injected_errors(http, path, body, kind, status) -> None:
    r = await http.post(
        path, json=body, headers={"x-mock-error": kind, "x-mock-retry-after-s": "3"}
    )
    assert r.status_code == status
    assert ("retry-after" in r.headers) == (status == 429)
    if status == 429:
        assert r.headers["retry-after"] == "3"


async def test_stream_cut_has_no_terminator(http) -> None:
    h = {"x-mock-error": "stream_cut"}
    r = await http.post("/v1/chat/completions", json={**OAI, "stream": True}, headers=h)
    assert (
        r.status_code == 200 and "[DONE]" not in r.text and '"finish_reason":"stop"' not in r.text
    )
    assert r.text.count('"content":"') < 8
    r = await http.post("/v1/messages", json={**ANT, "stream": True}, headers=h)
    assert (
        "message_start" in r.text and "message_stop" not in r.text and "message_delta" not in r.text
    )


async def test_random_errors_reproducible_with_seed() -> None:
    async def run(seed: int) -> list[int]:
        app = create_app(make_settings(mock_error_rate=0.5, mock_seed=seed))
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")
        return [(await c.post("/v1/chat/completions", json=OAI)).status_code for _ in range(30)]

    a, b, c = await run(1), await run(1), await run(2)
    assert a == b and a != c
    assert 5 < sum(s != 200 for s in a) < 25 and set(a) <= {200, 429, 500, 503}


async def test_same_seed_same_body_and_seed_changes_it(http) -> None:
    async def body(seed: str) -> dict:
        r = await http.post("/v1/chat/completions", json=OAI, headers={"x-mock-seed": seed})
        return r.json()

    assert await body("5") == await body("5")
    assert (await body("5"))["choices"] != (await body("6"))["choices"]


async def test_header_beats_control_beats_env(http) -> None:
    auth = {"authorization": f"Bearer {CONTROL_TOKEN}"}
    r = await http.put("/__control/openai", json={"error": "503"}, headers=auth)
    assert r.status_code == 200
    assert (await http.post("/v1/chat/completions", json=OAI)).status_code == 503
    assert (await http.post("/v1/messages", json=ANT)).status_code == 200  # scope khác
    assert (
        await http.post("/v1/chat/completions", json=OAI, headers={"x-mock-error": "none"})
    ).status_code == 200
    assert (await http.delete("/__control", headers=auth)).status_code == 200
    assert (await http.post("/v1/chat/completions", json=OAI)).status_code == 200


async def test_control_requires_token(http) -> None:
    assert (await http.put("/__control/openai", json={"error": "500"})).status_code == 401
    assert (
        await http.put(
            "/__control/nope", json={}, headers={"authorization": f"Bearer {CONTROL_TOKEN}"}
        )
    ).status_code == 404


async def test_required_key_401() -> None:
    app = create_app(make_settings(mock_required_key="k1"))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")
    assert (await c.post("/v1/chat/completions", json=OAI)).status_code == 401
    assert (await c.post("/v1/messages", json=ANT, headers={"x-api-key": "bad"})).status_code == 401
    assert (await c.post("/v1/messages", json=ANT, headers={"x-api-key": "k1"})).status_code == 200
    ok = await c.post("/v1/chat/completions", json=OAI, headers={"authorization": "Bearer k1"})
    assert ok.status_code == 200
    assert (
        await c.post("/v1beta/models/g:generateContent", json=GEM, params={"key": "k1"})
    ).status_code == 200


async def test_latency_ttft_and_token_delay() -> None:
    import time

    app = create_app(make_settings(mock_ttft_ms=100, mock_tokens_per_sec=100, mock_output_tokens=5))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")
    t = time.perf_counter()
    await c.post("/v1/chat/completions", json=OAI)
    assert time.perf_counter() - t >= 0.13  # 100ms + 4 * 10ms
    t = time.perf_counter()
    await c.post(
        "/v1/chat/completions",
        json=OAI,
        headers={"x-mock-ttft-ms": "0", "x-mock-token-delay-ms": "0"},
    )
    assert time.perf_counter() - t < 0.1


async def test_health_and_metrics(http) -> None:
    assert (await http.get("/healthz")).json() == {"status": "ok"}
    await http.post("/v1/chat/completions", json=OAI)
    await http.post("/v1/chat/completions", json=OAI, headers={"x-mock-error": "500"})
    assert (await http.get("/metrics")).status_code == 401
    text = (await http.get("/metrics", headers={"authorization": f"Bearer {METRICS_TOKEN}"})).text
    assert 'mock_requests_total{route="/v1/chat/completions",status="200"} 1' in text
    assert 'mock_requests_total{route="/v1/chat/completions",status="500"} 1' in text


# --- kịch bản nội dung (/__control/script) ---
_CTL = {"authorization": "Bearer control-secret"}
_TOOLS = [{"type": "function", "function": {"name": "prepare_close_ticket", "parameters": {}}}]


async def _chat(http: httpx.AsyncClient, text: str, tools: list | None = None) -> dict:
    body: dict = {"model": "m", "messages": [{"role": "user", "content": text}]}
    if tools:
        body["tools"] = tools
    r = await http.post("/v1/chat/completions", json=body)
    assert r.status_code == 200
    return r.json()["choices"][0]


async def test_script_text_and_tool_rules_consumed_in_order(http: httpx.AsyncClient) -> None:
    rules = [
        {"match": "router", "text": '{"route":"ticket","confidence":0.9}'},
        {
            "needs_tool": "prepare_close_ticket",
            "tool": "prepare_close_ticket",
            "args": {"code": "TCK-1"},
        },
    ]
    r = await http.put("/__control/script", json={"rules": rules}, headers=_CTL)
    assert r.status_code == 200
    c1 = await _chat(http, "you are a router")
    assert c1["message"]["content"] == '{"route":"ticket","confidence":0.9}'
    c2 = await _chat(http, "đóng ticket", _TOOLS)
    call = c2["message"]["tool_calls"][0]["function"]
    assert call["name"] == "prepare_close_ticket" and json.loads(call["arguments"]) == {
        "code": "TCK-1"
    }
    # hết lượt -> quay về câu trả lời tất định
    c3 = await _chat(http, "you are a router")
    assert c3["message"]["content"].startswith("mock")


async def test_script_tool_rule_not_forged_without_tool(http: httpx.AsyncClient) -> None:
    rules = [{"tool": "prepare_close_ticket", "args": {}}]
    await http.put("/__control/script", json={"rules": rules}, headers=_CTL)
    c = await _chat(http, "hi")  # request không có tools
    assert "tool_calls" not in c["message"]


async def test_script_rejects_bad_rule_and_reset_clears(http: httpx.AsyncClient) -> None:
    bad = await http.put(
        "/__control/script", json={"rules": [{"text": "a", "tool": "b"}]}, headers=_CTL
    )
    assert bad.status_code == 422
    await http.put("/__control/script", json={"rules": [{"text": "hello"}]}, headers=_CTL)
    assert (await http.delete("/__control", headers=_CTL)).status_code == 200
    assert (await http.get("/__control", headers=_CTL)).json()["script"] == []
    assert (await http.put("/__control/script", json={"rules": []})).status_code == 401
