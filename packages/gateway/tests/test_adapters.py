"""Test adapter `anthropic` (SDK chính thức -> wire Anthropic của mock_provider) và `mock`."""

from __future__ import annotations

import json

import anthropic
import httpx
import httpx2
import openai
import pytest
from fastapi import FastAPI
from gateway.adapters.anthropic import AnthropicChatProvider, build_params
from gateway.adapters.openai_chat import OpenAIChatProvider
from gateway.container import build_container
from gateway.main import create_app
from gateway.ports.types import ChatRequest, ProviderError
from gateway.testing import provider_lookup
from gw_support import Env, make_mock_app, make_settings

PING = {
    "type": "function",
    "function": {"name": "ping", "description": "p", "parameters": {"type": "object"}},
}


def anthropic_provider(app: FastAPI) -> AnthropicChatProvider:
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
    client = anthropic.AsyncAnthropic(
        base_url="http://mock", api_key="k", http_client=http, max_retries=0
    )
    return AnthropicChatProvider("k", client=client)


def req(content: str = "hello", **kw: object) -> ChatRequest:
    base: dict = {
        "alias": "acme-fast",
        "model": "claude-haiku-5-5",
        "messages": [{"role": "user", "content": content}],
        "params": {"max_tokens": 100},
    }
    return ChatRequest(**{**base, **kw})


async def test_complete_and_usage() -> None:
    p = anthropic_provider(make_mock_app())
    r = await p.complete(req())
    assert r.provider == "anthropic" and r.finish_reason == "stop"
    assert r.message["content"] and r.usage.completion_tokens == 8 and r.usage.prompt_tokens > 0


async def test_stream_matches_complete() -> None:
    p = anthropic_provider(make_mock_app())
    full = await p.complete(req())
    chunks = [c async for c in p.stream(req(stream=True))]
    assert "".join(c.text or "" for c in chunks) == full.message["content"]
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["stop"]
    usage = [c.usage for c in chunks if c.usage][-1]
    assert usage.completion_tokens == 8 and usage.prompt_tokens == full.usage.prompt_tokens


async def test_tool_call_both_ways() -> None:
    p = anthropic_provider(make_mock_app())
    r = req('call_tool:ping {"n":2}', tools=[PING])
    full = await p.complete(r)
    call = full.message["tool_calls"][0]
    assert full.finish_reason == "tool_calls" and call["function"]["name"] == "ping"
    assert json.loads(call["function"]["arguments"]) == {"n": 2}
    name, args, idx = None, "", set()
    async for c in p.stream(r):
        if c.tool_call:
            name = c.tool_call.name or name
            args += c.tool_call.arguments
            idx.add(c.tool_call.index)
    assert name == "ping" and json.loads(args) == {"n": 2} and idx == {0}


def test_build_params_translation() -> None:
    messages = [
        {"role": "system", "content": "be brief"},
        {"role": "developer", "content": "be kind"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "ping", "arguments": '{"n":1}'}},
            {"id": "c2", "type": "function", "function": {"name": "ping", "arguments": "oops"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "pong"},
        {"role": "tool", "tool_call_id": "c2", "content": "pong2"},
        {"role": "assistant", "content": ""},  # rỗng: bỏ
        {"role": "user", "content": [{"type": "text", "text": "thanks"}]},
    ]  # fmt: skip
    r = req(
        messages=messages, tools=[PING], tool_choice="required",
        params={"max_tokens": 50, "temperature": 1.7, "stop": "END", "parallel_tool_calls": False},
    )  # fmt: skip
    p = build_params(r)
    assert p["system"] == "be brief\n\nbe kind" and p["max_tokens"] == 50
    assert p["temperature"] == 1.0 and p["stop_sequences"] == ["END"]
    assert p["tools"][0] == {"name": "ping", "description": "p", "input_schema": {"type": "object"}}
    assert p["tool_choice"] == {"type": "any", "disable_parallel_tool_use": True}
    roles = [m["role"] for m in p["messages"]]
    assert roles == ["user", "assistant", "user"]  # tool results gộp vào message user liền sau
    assistant = p["messages"][1]["content"]
    assert [b["type"] for b in assistant] == ["tool_use", "tool_use"]
    assert assistant[0]["input"] == {"n": 1} and assistant[1]["input"] == {}
    user = p["messages"][2]["content"]
    assert [b["type"] for b in user] == ["tool_result", "tool_result", "text"]
    assert user[0]["tool_use_id"] == "c1"


def test_build_params_tool_choice_variants() -> None:
    forced = {"type": "function", "function": {"name": "ping"}}
    assert build_params(req(tools=[PING], tool_choice=forced))["tool_choice"] == {
        "type": "tool", "name": "ping",
    }  # fmt: skip
    assert build_params(req(tools=[PING], tool_choice="auto"))["tool_choice"] == {"type": "auto"}
    none = build_params(req(tools=[PING], tool_choice="none"))
    assert "tools" not in none and "tool_choice" not in none


def test_build_params_images() -> None:
    parts = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
    ]
    p = build_params(req(messages=[{"role": "user", "content": parts}]))
    src = [b["source"] for b in p["messages"][0]["content"]]
    assert src[0] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}
    assert src[1] == {"type": "url", "url": "https://x/y.png"}


@pytest.mark.parametrize(
    ("kind", "status", "retryable"),
    [("429", 429, True), ("500", 500, True), ("503", 503, True), ("timeout", 504, True)],
)
async def test_errors_map_to_provider_error(kind: str, status: int, retryable: bool) -> None:
    app = make_mock_app(mock_error_kinds=kind)
    app.state.ctx.overrides["*"] = {"error": kind, "retry_after_s": 7}
    p = anthropic_provider(app)
    with pytest.raises(ProviderError) as e:
        await p.complete(req())
    assert e.value.kind == f"http_{status}" and e.value.retryable is retryable
    assert "mock" not in str(e.value) and "http://" not in str(e.value)  # không lộ URL
    if status == 429:
        assert e.value.retry_after_s == 7


async def test_stream_cut_is_protocol_error() -> None:
    app = make_mock_app()
    app.state.ctx.overrides["*"] = {"error": "stream_cut"}
    p = anthropic_provider(app)
    with pytest.raises(ProviderError) as e:
        _ = [c async for c in p.stream(req())]
    assert e.value.kind == "protocol"


async def test_gateway_end_to_end_with_anthropic_adapter(env: Env) -> None:
    """Không override: alias acme-fast -> provider `anthropic`, model id từ models.yaml."""
    settings = make_settings(gw_provider_override=None)
    adapter = anthropic_provider(env.mock_app)
    c = build_container(
        settings, clock=env.clock, keys=env.keys, verifier=env.verifier, sink=env.sink,
        providers=provider_lookup(anthropic=adapter),
    )  # fmt: skip
    env.app = create_app(settings, c)
    key = await env.new_key()
    client = openai.AsyncOpenAI(
        base_url="http://gateway/v1", api_key=key, max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app)),
    )  # fmt: skip
    raw = await client.chat.completions.with_raw_response.create(
        model="acme-fast", messages=[{"role": "user", "content": "hello"}]
    )
    assert raw.headers["x-acme-provider"] == "anthropic"
    assert raw.headers["x-acme-model"] == "claude-haiku-5-5"
    assert raw.parse().usage.completion_tokens == 8


async def test_mock_adapter_errors() -> None:
    app = make_mock_app()
    app.state.ctx.overrides["*"] = {"error": "429", "retry_after_s": 3}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")
    p = OpenAIChatProvider("http://mock", client=client)
    with pytest.raises(ProviderError) as e:
        await p.complete(req())
    assert e.value.kind == "http_429" and e.value.retryable and e.value.retry_after_s == 3


def test_bearer_header_only_with_key() -> None:
    with_key = OpenAIChatProvider("http://x", api_key="sk-1", name="openrouter")
    without = OpenAIChatProvider("http://x")
    assert with_key._client.headers["authorization"] == "Bearer sk-1"
    assert with_key.name == "openrouter" and without.name == "openai_chat"
    assert "authorization" not in without._client.headers
