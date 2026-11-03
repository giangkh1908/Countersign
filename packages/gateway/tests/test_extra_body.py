"""`extra_body` theo alias: catalog đọc, service truyền xuống provider, adapter gộp vào body, khoá cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from acme_common.ports import Principal
from acme_common.testing import FakeClock, FakeEventSink, FakeTokenVerifier
from gateway.adapters.anthropic import build_params
from gateway.adapters.openai_chat import OpenAIChatProvider
from gateway.container import build_container
from gateway.main import create_app
from gateway.ports.types import ChatChunk, ChatRequest, ChatResponse, Usage
from gateway.services.cache_key import build_cache_key
from gateway.services.catalog import ModelCatalog
from gateway.services.errors import GatewayError
from gateway.services.key_admin import issue_key
from gateway.testing import FakeChatProvider, FakeKeyStore, provider_lookup
from gw_support import ALL_ALIASES, PEPPER, make_settings

REASONING = {"reasoning": {"enabled": False}}
MSG = [{"role": "user", "content": "hi"}]


def catalog(**alias: Any) -> ModelCatalog:
    return ModelCatalog({"aliases": {"a": {"chain": ["mock/m"], **alias}}})


def test_catalog_reads_extra_body() -> None:
    assert catalog(extra_body=REASONING).resolve("a").extra_body == REASONING


def test_catalog_extra_body_defaults_to_empty() -> None:
    assert catalog(timeout_s=5).resolve("a").extra_body == {}


@pytest.mark.parametrize("bad", [[1, 2], "oops", 3])
def test_catalog_extra_body_wrong_type_is_config_error(bad: Any) -> None:
    with pytest.raises(GatewayError):
        catalog(extra_body=bad).resolve("a")


def test_shipped_chat_aliases_disable_reasoning() -> None:
    cat = ModelCatalog.from_file(Path(__file__).resolve().parents[1] / "config" / "models.yaml")
    for alias in ("acme-fast", "acme-smart", "acme-judge"):
        assert cat.resolve(alias).extra_body == REASONING


async def sent_body(**kw: Any) -> dict[str, Any]:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        msg = {"role": "assistant", "content": "ok"}
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": msg, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    provider = OpenAIChatProvider("http://x", client=client)
    await provider.complete(ChatRequest(alias="a", model="real-model", messages=MSG, **kw))
    return seen[0]


async def test_openai_adapter_merges_extra_body() -> None:
    body = await sent_body(extra_body=REASONING)
    assert body["reasoning"] == {"enabled": False}
    assert body["model"] == "real-model" and body["stream"] is False


async def test_openai_adapter_extra_body_cannot_override_core_fields() -> None:
    body = await sent_body(
        extra_body={"model": "evil", "messages": [], "stream": True, "stream_options": {"x": 1}}
    )
    assert body["model"] == "real-model"
    assert body["messages"] == MSG
    assert body["stream"] is False and "stream_options" not in body


async def test_openai_adapter_without_extra_body_unchanged() -> None:
    assert "reasoning" not in await sent_body()


def test_anthropic_passes_extra_body_only_when_set() -> None:
    assert "extra_body" not in build_params(ChatRequest(alias="a", model="m", messages=MSG))
    req = ChatRequest(alias="a", model="m", messages=MSG, extra_body=REASONING)
    assert build_params(req)["extra_body"] == REASONING


def test_cache_key_depends_on_extra_body_only_when_present() -> None:
    u = Principal(
        sub="u",
        audience=("llm-gateway",),
        azp="c",
        scopes=frozenset(),
        expires_at=2e9,
        dept=("IT",),
        clearance=1,
        roles=("staff",),
    )
    args: dict[str, Any] = {
        "user": u,
        "provider": "p",
        "model": "m",
        "messages": [],
        "params": {},
        "tools": None,
        "tool_choice": None,
        "index_version": "0",
    }
    plain = build_cache_key(**args)
    assert build_cache_key(**args, extra_body={}) == plain
    assert build_cache_key(**args, extra_body=REASONING) != plain


async def test_service_forwards_alias_extra_body_to_provider(tmp_path: Path) -> None:
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "aliases:\n"
        "  acme-fast: { chain: [mock/m1], extra_body: { reasoning: { enabled: false } } }\n"
        "  acme-smart: { chain: [mock/m1] }\n",
        encoding="utf8",
    )
    reply = ChatResponse({"role": "assistant", "content": "ok"}, "stop", Usage(1, 1), "m", "fake")
    provider = FakeChatProvider(
        response=reply,
        chunks=[ChatChunk(text="ok"), ChatChunk(finish_reason="stop", usage=Usage(1, 1))],
    )
    keys = FakeKeyStore()
    settings = make_settings(gw_models_config=str(cfg))
    c = build_container(
        settings,
        clock=FakeClock(),
        keys=keys,
        verifier=FakeTokenVerifier(),
        sink=FakeEventSink(),
        providers=provider_lookup(mock=provider),
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
    )
    await keys.create(issued.new, "t")
    app = create_app(settings, c)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gw",
        headers={"authorization": f"Bearer {issued.plaintext}"},
    ) as client:
        for model in ("acme-fast", "acme-smart"):
            r = await client.post("/v1/chat/completions", json={"model": model, "messages": MSG})
            assert r.status_code == 200
    assert [q.extra_body for q in provider.requests] == [REASONING, {}]
