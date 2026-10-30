"""Gọi gateway bằng chính SDK `openai` và `langchain_openai`; provider sau lưng là mock_provider in-process."""

from __future__ import annotations

import json

import httpx
import openai
import pytest
from gw_support import Env
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

USAGE_COLUMNS = {
    "request_id", "key_id", "department", "end_user_sub", "alias", "provider", "model",
    "input_tokens", "output_tokens", "cached_input_tokens", "cost_micro_usd", "latency_ms",
    "ttft_ms", "gateway_overhead_ms", "sidecar_ms", "cache", "fallback_count", "route_reason",
    "pii_entities", "guard_score", "status_code", "error_code",
}  # fmt: skip

PING = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "ping",
        "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}},
    },
}


def sdk(env: Env, key: str) -> openai.AsyncOpenAI:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app))
    return openai.AsyncOpenAI(
        base_url="http://gateway/v1", api_key=key, http_client=http, max_retries=0
    )


def usage_events(env: Env) -> list[dict]:
    return [e for e in env.sink.events if e.get("event") == "usage"]


async def test_non_stream(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    raw = await client.chat.completions.with_raw_response.create(
        model="acme-fast", messages=[{"role": "user", "content": "hello"}]
    )
    r = raw.parse()
    assert r.model == "acme-fast"  # alias client gửi
    assert r.choices[0].message.content and r.choices[0].finish_reason == "stop"
    assert r.usage and r.usage.completion_tokens == 8
    h = raw.headers
    assert h["x-acme-provider"] == "mock" and h["x-acme-model"] == "claude-haiku-5-5"
    assert h["x-acme-request-id"] and h["x-acme-fallbacks"] == "0"
    assert r.id == f"chatcmpl-{h['x-acme-request-id']}"


async def test_model_id_comes_from_models_yaml(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    raw = await client.chat.completions.with_raw_response.create(
        model="acme-smart", messages=[{"role": "user", "content": "hi"}]
    )
    assert raw.headers["x-acme-model"] == "claude-sonnet-5-5"
    assert usage_events(env)[0]["model"] == "claude-sonnet-5-5"


async def test_stream_with_usage(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    msgs = [{"role": "user", "content": "hello"}]
    full = await client.chat.completions.create(model="acme-fast", messages=msgs)
    stream = await client.chat.completions.create(
        model="acme-fast", messages=msgs, stream=True, stream_options={"include_usage": True}
    )
    text, usage, finish, extra = "", None, None, None
    async for chunk in stream:
        if chunk.choices:
            text += chunk.choices[0].delta.content or ""
            finish = chunk.choices[0].finish_reason or finish
        if chunk.usage:
            usage, extra = chunk.usage, chunk.model_extra
    assert text == full.choices[0].message.content
    assert finish == "stop"
    assert usage and usage.completion_tokens == 8
    assert extra and extra["x_acme"]["provider"] == "mock" and extra["x_acme"]["request_id"]


async def test_stream_without_include_usage_has_no_usage_chunk(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    stream = await client.chat.completions.create(
        model="acme-fast", messages=[{"role": "user", "content": "hello"}], stream=True
    )
    chunks = [c async for c in stream]
    assert chunks and all(c.usage is None for c in chunks)


async def test_tool_call_non_stream(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    r = await client.chat.completions.create(
        model="acme-fast",
        messages=[{"role": "user", "content": 'call_tool:ping {"n":2}'}],
        tools=[PING],
    )
    call = r.choices[0].message.tool_calls[0]
    assert r.choices[0].finish_reason == "tool_calls"
    assert call.function.name == "ping" and json.loads(call.function.arguments) == {"n": 2}


async def test_tool_call_stream(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    stream = await client.chat.completions.create(
        model="acme-fast",
        messages=[{"role": "user", "content": 'call_tool:ping {"n":2}'}],
        tools=[PING],
        stream=True,
    )
    name, args, finish = None, "", None
    async for chunk in stream:
        ch = chunk.choices[0]
        for tc in ch.delta.tool_calls or []:
            name = (tc.function.name if tc.function and tc.function.name else None) or name
            args += tc.function.arguments or ""
        finish = ch.finish_reason or finish
    assert name == "ping" and json.loads(args) == {"n": 2} and finish == "tool_calls"


async def test_tool_result_roundtrip_is_accepted(env: Env, api_key: str) -> None:
    """Chiều ngược: assistant tool_calls + message role=tool gửi lại gateway."""
    client = sdk(env, api_key)
    msgs = [
        {"role": "user", "content": "echo: done"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "pong"},
    ]
    r = await client.chat.completions.create(model="acme-fast", messages=msgs, tools=[PING])
    assert r.choices[0].message.content


async def test_max_tokens_truncates(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    r = await client.chat.completions.create(
        model="acme-fast", messages=[{"role": "user", "content": "hello"}], max_tokens=3
    )
    assert r.choices[0].finish_reason == "length" and r.usage.completion_tokens == 3


async def test_acme_auto_resolves_to_simple_alias(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    raw = await client.chat.completions.with_raw_response.create(
        model="acme-auto", messages=[{"role": "user", "content": "hi"}]
    )
    assert raw.headers["x-acme-model"] == "claude-haiku-5-5"
    ev = usage_events(env)[0]
    assert ev["alias"] == "acme-fast" and ev["route_reason"] == "static_simple"


async def test_usage_event_fields_and_tokens(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    secret_prompt = "SUPER-SECRET-PROMPT-TEXT"
    r = await client.chat.completions.create(
        model="acme-fast", messages=[{"role": "user", "content": secret_prompt}]
    )
    (ev,) = usage_events(env)
    assert set(ev) >= USAGE_COLUMNS
    assert ev["input_tokens"] == r.usage.prompt_tokens > 0
    assert ev["output_tokens"] == r.usage.completion_tokens == 8
    assert ev["status_code"] == 200 and ev["error_code"] is None
    assert ev["department"] == "IT" and ev["end_user_sub"] is None
    assert ev["provider"] == "mock" and ev["alias"] == "acme-fast"
    assert ev["cache"] == "miss" and ev["fallback_count"] == 0
    assert ev["request_id"] == r.id.removeprefix("chatcmpl-")
    assert secret_prompt not in json.dumps(env.sink.events, default=str)


async def test_stream_usage_event_matches_provider(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    stream = await client.chat.completions.create(
        model="acme-fast", messages=[{"role": "user", "content": "hello"}], stream=True
    )
    _ = [c async for c in stream]
    (ev,) = usage_events(env)
    assert ev["output_tokens"] == 8 and ev["input_tokens"] > 0
    assert ev["ttft_ms"] is not None and ev["status_code"] == 200


async def test_invalid_request_n_gt_1(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    with pytest.raises(openai.BadRequestError) as e:
        await client.chat.completions.create(
            model="acme-fast", messages=[{"role": "user", "content": "x"}], n=2
        )
    assert e.value.code == "invalid_request"


async def test_model_not_allowed(env: Env) -> None:
    key = await env.new_key(allowed_models=("acme-fast",))
    client = sdk(env, key)
    with pytest.raises(openai.PermissionDeniedError) as e:
        await client.chat.completions.create(
            model="acme-smart", messages=[{"role": "user", "content": "x"}]
        )
    assert e.value.code == "model_not_allowed"
    assert usage_events(env) == []


async def test_provider_error_maps_to_502_and_is_recorded(env: Env, api_key: str) -> None:
    env.mock_app.state.ctx.overrides["*"] = {"error": "500"}
    client = sdk(env, api_key)
    with pytest.raises(openai.InternalServerError) as e:
        await client.chat.completions.create(
            model="acme-fast", messages=[{"role": "user", "content": "x"}]
        )
    assert e.value.status_code == 502 and e.value.code == "all_providers_failed"
    (ev,) = usage_events(env)
    assert ev["status_code"] == 502 and ev["error_code"] == "all_providers_failed"


async def test_provider_error_before_first_byte_in_stream_is_http_error(
    env: Env, api_key: str
) -> None:
    env.mock_app.state.ctx.overrides["*"] = {"error": "503"}
    client = sdk(env, api_key)
    with pytest.raises(openai.InternalServerError):
        await client.chat.completions.create(
            model="acme-fast", messages=[{"role": "user", "content": "x"}], stream=True
        )


async def test_stream_cut_midway_yields_error_chunk_and_done(env: Env, api_key: str) -> None:
    env.mock_app.state.ctx.overrides["*"] = {"error": "stream_cut"}
    async with env.gateway_client(api_key) as http:
        body = {
            "model": "acme-fast",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }
        r = await http.post("http://gateway/v1/chat/completions", json=body)
    lines = [ln for ln in r.text.splitlines() if ln.startswith("data:")]
    assert lines[-1] == "data: [DONE]"
    assert json.loads(lines[-2][5:])["error"]["code"] == "all_providers_failed"
    (ev,) = usage_events(env)
    assert ev["status_code"] == 502


# ---- langchain_openai ----


class Ping(BaseModel):
    """ping"""

    n: int


def chat_model(env: Env, key: str, **kw: object) -> ChatOpenAI:
    return ChatOpenAI(
        model="acme-fast",
        base_url="http://gateway/v1",
        api_key=key,  # type: ignore[arg-type]
        http_async_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app)),
        max_retries=0,
        **kw,  # type: ignore[arg-type]
    )


async def test_langchain_invoke_and_stream(env: Env, api_key: str) -> None:
    llm = chat_model(env, api_key)
    msg = await llm.ainvoke([HumanMessage("hello")])
    assert msg.content and msg.usage_metadata and msg.usage_metadata["output_tokens"] == 8
    parts = [c async for c in llm.astream([HumanMessage("hello")])]
    assert "".join(str(p.content) for p in parts) == msg.content


async def test_langchain_tool_call(env: Env, api_key: str) -> None:
    llm = chat_model(env, api_key).bind_tools([Ping])
    msg = await llm.ainvoke([HumanMessage('call_tool:Ping {"n":2}')])
    assert msg.tool_calls and msg.tool_calls[0]["name"] == "Ping"
    assert msg.tool_calls[0]["args"] == {"n": 2}
