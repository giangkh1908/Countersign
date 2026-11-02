"""Exact cache ở ChatService: hit/miss, cách ly theo phạm vi quyền, các trường hợp không cache."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from acme_common.ports import Principal
from acme_common.testing import FakeClock, FakeEventSink, FakeTokenVerifier
from gateway.adapters.redis import RedisResponseCache
from gateway.container import build_container
from gateway.factory import build_response_cache
from gateway.main import create_app
from gateway.ports import CachedResponse, CacheNotConfigured, ResponseCache
from gateway.ports.types import ChatChunk, ChatResponse, ToolCallDelta, Usage
from gateway.services.key_admin import issue_key
from gateway.testing import FakeChatProvider, FakeKeyStore, FakeResponseCache, provider_lookup
from gw_support import ALL_ALIASES, PEPPER, make_settings

CANARY = "CANARY-9f3a-noi-dung-cau-hoi"


def principal(
    dept: tuple[str, ...] = ("IT",),
    clearance: int | None = 1,
    roles: tuple[str, ...] = ("staff",),
) -> Principal:
    return Principal(
        sub="u",
        audience=("llm-gateway",),
        azp="chat-ui",
        scopes=frozenset(),
        expires_at=2e9,
        dept=dept,
        clearance=clearance,
        roles=roles,
    )


def reply(text: str = "Trả lời [#1]", finish: str = "stop") -> ChatResponse:
    return ChatResponse(
        {"role": "assistant", "content": text}, finish, Usage(10, 5), "model-x", "fake"
    )


@dataclass
class Rig:
    cache: FakeResponseCache
    provider: FakeChatProvider
    sink: FakeEventSink
    verifier: FakeTokenVerifier
    key: str
    app: Any
    container: Any

    def client(self, token: str | None = "t-it") -> httpx.AsyncClient:
        headers = {"authorization": f"Bearer {self.key}"}
        if token:
            headers["x-acme-user-token"] = token
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://gw", headers=headers
        )


async def make_rig(
    *,
    cache: FakeResponseCache | None = None,
    provider: FakeChatProvider | None = None,
    version: str = "0",
) -> Rig:
    cache = cache or FakeResponseCache()
    provider = provider or FakeChatProvider(
        response=reply(), chunks=[ChatChunk(text="Trả lời "), ChatChunk(text="[#1]")]
    )
    if provider.chunks and provider.chunks[-1].finish_reason is None:
        provider.chunks.append(ChatChunk(finish_reason="stop", usage=Usage(10, 5)))
    sink, keys = FakeEventSink(), FakeKeyStore()
    verifier = FakeTokenVerifier(
        {
            "t-it": principal(),
            "t-it2": principal(),
            "t-hr": principal(dept=("HR",)),
            "t-clr": principal(clearance=3),
            "t-mgr": principal(roles=("manager",)),
        }
    )
    settings = make_settings(gw_cache_index_version=version)
    c = build_container(
        settings,
        clock=FakeClock(),
        keys=keys,
        verifier=verifier,
        sink=sink,
        providers=provider_lookup(mock=provider),
        cache=cache,
    )
    issued = issue_key(
        PEPPER.encode(),
        name="t",
        owner_type="service",
        owner_ref="t",
        dept="IT",
        allowed_models=ALL_ALIASES,
        rpm=60,
        tpm=100_000,
        trust_end_user_token=True,
    )
    await keys.create(issued.new, "t")
    return Rig(cache, provider, sink, verifier, issued.plaintext, create_app(settings, c), c)


def body(text: str = f"cau hoi {CANARY}", **extra: Any) -> dict[str, Any]:
    return {"model": "acme-fast", "messages": [{"role": "user", "content": text}], **extra}


async def ask(rig: Rig, token: str | None = "t-it", **extra: Any) -> httpx.Response:
    async with rig.client(token) as c:
        return await c.post("/v1/chat/completions", json=body(**extra))


async def test_second_identical_request_hits_without_calling_provider() -> None:
    rig = await make_rig()
    r1 = await ask(rig)
    r2 = await ask(rig)
    assert r1.headers["x-acme-cache"] == "miss" and r2.headers["x-acme-cache"] == "exact"
    assert len(rig.provider.requests) == 1
    assert r1.json()["choices"] == r2.json()["choices"]  # trích dẫn [#1] giữ nguyên
    assert r2.json()["choices"][0]["message"]["content"] == "Trả lời [#1]"
    events = [e for e in rig.sink.events if e["event"] == "usage_event"]
    assert [e["cache"] for e in events] == ["miss", "exact"]
    assert events[1]["input_tokens"] == 0 and events[1]["cost_micro_usd"] == 0
    assert list(rig.cache.ttls.values()) == [3600]


@pytest.mark.parametrize("other", ["t-hr", "t-clr", "t-mgr"])
async def test_different_scope_does_not_hit(other: str) -> None:
    rig = await make_rig()
    await ask(rig, "t-it")
    r = await ask(rig, other)
    assert r.headers["x-acme-cache"] == "miss"
    assert len(rig.provider.requests) == 2
    assert len(rig.cache.items) == 2  # hai entry riêng
    # entry của phạm vi này không bị phạm vi kia đọc ngược lại
    assert (await ask(rig, "t-it")).headers["x-acme-cache"] == "exact"
    assert (await ask(rig, other)).headers["x-acme-cache"] == "exact"
    assert len(rig.provider.requests) == 2


async def test_same_scope_different_user_shares_entry() -> None:
    rig = await make_rig()
    await ask(rig, "t-it")
    assert (await ask(rig, "t-it2")).headers["x-acme-cache"] == "exact"


async def test_changing_index_version_invalidates_old_entries() -> None:
    cache = FakeResponseCache()
    old = await make_rig(cache=cache, version="1")
    await ask(old)
    new = await make_rig(cache=cache, version="2")
    r = await ask(new)
    assert r.headers["x-acme-cache"] == "miss" and len(new.provider.requests) == 1


async def test_no_user_token_bypasses_cache() -> None:
    rig = await make_rig()
    r1, r2 = await ask(rig, None), await ask(rig, None)
    assert r1.headers["x-acme-cache"] == r2.headers["x-acme-cache"] == "bypass"
    assert not rig.cache.items and len(rig.provider.requests) == 2


TOOLS = [{"type": "function", "function": {"name": "search_documents", "parameters": {}}}]
TOOLS2 = [{"type": "function", "function": {"name": "create_ticket", "parameters": {}}}]
TOOL_TURN = [
    {"role": "user", "content": f"hoi {CANARY}"},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_documents"}}],
    },
    {"role": "tool", "tool_call_id": "c1", "content": "doan van [#1]"},
]


async def ask_agent(rig: Rig, token: str | None = "t-it", tools: Any = TOOLS) -> httpx.Response:
    async with rig.client(token) as c:
        return await c.post(
            "/v1/chat/completions",
            json={"model": "acme-fast", "messages": TOOL_TURN, "tools": tools},
        )


async def test_tool_call_response_with_tools_request_is_never_stored() -> None:
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "1", "type": "function", "function": {"name": "create_ticket"}}],
    }
    rig = await make_rig(
        provider=FakeChatProvider(
            response=ChatResponse(msg, "tool_calls", Usage(1, 1), "m", "fake")
        )
    )
    r1, r2 = await ask_agent(rig, tools=TOOLS2), await ask_agent(rig, tools=TOOLS2)
    assert r1.headers["x-acme-cache"] == r2.headers["x-acme-cache"] == "miss"
    assert not rig.cache.items and len(rig.provider.requests) == 2  # luôn gọi provider


async def test_agent_final_answer_with_tools_and_tool_turn_is_cached() -> None:
    rig = await make_rig()
    r1 = await ask_agent(rig)
    r2 = await ask_agent(rig)
    assert r1.headers["x-acme-cache"] == "miss" and r2.headers["x-acme-cache"] == "exact"
    assert len(rig.provider.requests) == 1
    assert "tool_calls" not in r2.json()["choices"][0]["message"]  # hit không phát lại tool call
    assert r2.json()["choices"][0]["message"]["content"] == "Trả lời [#1]"
    # khác phạm vi thì miss; khác danh sách tools thì miss
    assert (await ask_agent(rig, "t-hr")).headers["x-acme-cache"] == "miss"
    assert (await ask_agent(rig, tools=TOOLS2)).headers["x-acme-cache"] == "miss"
    assert (await ask_agent(rig, "t-hr")).headers["x-acme-cache"] == "exact"
    assert len(rig.provider.requests) == 3


async def test_stored_entries_never_contain_tool_calls() -> None:
    rig = await make_rig()
    await ask_agent(rig)
    assert rig.cache.items and all(
        "tool_calls" not in v.content and v.finish_reason == "stop"
        for v in rig.cache.items.values()
    )


async def test_non_stop_finish_is_not_stored() -> None:
    rig = await make_rig(provider=FakeChatProvider(response=reply(finish="length")))
    await ask(rig)
    assert not rig.cache.items
    assert (await ask(rig)).headers["x-acme-cache"] == "miss"


async def test_tool_call_response_is_not_stored() -> None:
    msg = {"role": "assistant", "content": "x", "tool_calls": [{"id": "1"}]}
    rig = await make_rig(
        provider=FakeChatProvider(response=ChatResponse(msg, "stop", Usage(1, 1), "m", "fake"))
    )
    await ask(rig)
    assert not rig.cache.items


async def test_provider_error_is_not_stored() -> None:
    from gateway.ports.types import ProviderError

    rig = await make_rig(provider=FakeChatProvider(error=ProviderError("timeout")))
    r = await ask(rig)
    assert r.status_code == 502 and not rig.cache.items


async def test_cache_down_degrades_to_miss_and_still_answers() -> None:
    rig = await make_rig(cache=FakeResponseCache(fail=True))
    r = await ask(rig)
    assert r.status_code == 200 and r.headers["x-acme-cache"] == "miss"
    text = rig.container.metrics.render().decode()
    assert 'gateway_cache_lookups_total{result="error"} 1.0' in text
    assert 'gateway_cache_stores_total{result="error"} 1.0' in text


async def test_model_not_allowed_checked_before_cache() -> None:
    rig = await make_rig()
    await ask(rig)
    async with rig.client() as c:
        r = await c.post("/v1/chat/completions", json={**body(), "model": "khong-co"})
    assert r.status_code in (400, 403, 404)
    assert "x-acme-cache" not in r.headers


async def _sse_text(r: httpx.Response) -> tuple[str, bool]:
    text, usage = "", False
    for line in r.text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        d = json.loads(line[6:])
        usage = usage or "usage" in d
        for ch in d["choices"]:
            text += ch["delta"].get("content") or ""
    return text, usage


async def test_stream_miss_stores_then_stream_hit_replays_sse() -> None:
    rig = await make_rig()
    opts = {"stream": True, "stream_options": {"include_usage": True}}
    r1 = await ask(rig, **opts)
    t1 = await _sse_text(r1)
    r2 = await ask(rig, **opts)
    t2 = await _sse_text(r2)
    assert r1.headers["x-acme-cache"] == "miss" and r2.headers["x-acme-cache"] == "exact"
    assert t1 == t2 == ("Trả lời [#1]", True)
    assert r2.text.rstrip().endswith("data: [DONE]")
    assert len(rig.provider.requests) == 1
    # non-stream cùng nội dung dùng lại entry của stream
    assert (await ask(rig)).headers["x-acme-cache"] == "exact"


async def test_stream_with_tool_call_or_length_not_stored() -> None:
    chunks = [
        ChatChunk(text="a"),
        ChatChunk(tool_call=ToolCallDelta(0, "1", "f", "{}")),
        ChatChunk(finish_reason="stop", usage=Usage(1, 1)),
    ]
    rig = await make_rig(provider=FakeChatProvider(chunks=chunks))
    await _sse_text(await ask(rig, stream=True))
    assert not rig.cache.items


async def test_cache_never_leaks_content_into_metrics_or_spans() -> None:
    rig = await make_rig()
    await ask(rig)
    await ask(rig)
    assert CANARY not in rig.container.metrics.render().decode()


def test_factory_known_unknown_and_off() -> None:
    assert build_response_cache("off", make_settings()) is None
    c = build_response_cache(
        "redis", make_settings(gw_cache_redis_url="redis://gwcache:pw@redis-cache:6379/0")
    )
    assert isinstance(c, ResponseCache) and isinstance(c, RedisResponseCache)
    with pytest.raises(CacheNotConfigured, match="GW_CACHE_REDIS_URL"):
        build_response_cache("redis", make_settings())
    with pytest.raises(CacheNotConfigured) as e:
        build_response_cache("nope", make_settings())
    assert "redis" in str(e.value) and "off" in str(e.value)


async def test_redis_adapter_roundtrip_ttl_and_corrupt_entry() -> None:
    import fakeredis

    cache = RedisResponseCache("redis://localhost:1/0", max_value_bytes=2000)
    cache._redis = fakeredis.FakeAsyncRedis()  # type: ignore[assignment]
    v = CachedResponse("nội dung [#1]", "stop", 7, 3, "mock", "m1")
    assert await cache.get("k") is None
    await cache.put("k", v, 60)
    assert await cache.get("k") == v
    assert 0 < await cache._redis.ttl("k") <= 60
    await cache._redis.set("bad", b"{not json")
    assert await cache.get("bad") is None
    await cache.put("big", CachedResponse("x" * 5000, "stop", 1, 1, "p", "m"), 60)
    assert await cache.get("big") is None  # quá cỡ thì không lưu
    await cache.aclose()
