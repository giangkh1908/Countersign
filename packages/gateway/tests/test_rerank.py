"""`POST /v1/rerank`: route, service, adapter `http_rerank` (respx), factory, catalog, `update-key-models`."""

from __future__ import annotations

import io
import json

import httpx
import pytest
from acme_common import telemetry
from acme_common.http import RetryingHttpClient
from acme_common.testing import FakeClock, FakeEventSink
from gateway.adapters.http_rerank import HttpRerankProvider
from gateway.cli import parser, update_key_models
from gateway.container import build_container
from gateway.factory import build_rerank_provider
from gateway.main import create_app
from gateway.ports import ProviderError, RerankNotConfigured, RerankProvider
from gateway.services.catalog import ModelCatalog
from gateway.services.errors import GatewayError
from gateway.services.key_admin import parse_key
from gateway.testing import FakeKeyStore, FakeRerankProvider
from gw_support import Env, make_settings
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

CANARY = "CANARY-9d1f-truy-van"
DOCS = [f"đoạn số {i} {CANARY}" for i in range(4)]


def rerank_env(env: Env, provider: RerankProvider) -> Env:
    """Dựng lại app với catalog có alias `acme-rerank` và provider tiêm sẵn."""
    import tempfile
    from pathlib import Path

    cfg = Path(tempfile.mkdtemp()) / "models.yaml"
    cfg.write_text(
        "aliases:\n  acme-rerank: {kind: rerank, adapter: http_rerank, model: m-rerank,"
        " base_url: 'http://x'}\n",
        encoding="utf8",
    )
    settings = make_settings(gw_models_config=str(cfg))
    c = build_container(
        settings,
        clock=env.clock,
        keys=env.keys,
        verifier=env.verifier,
        sink=env.sink,
        providers=env.providers,
        rerankers=lambda _spec: provider,
    )
    env.app = create_app(settings, c)
    return env


def usage_events(env: Env) -> list[dict]:
    return [e for e in env.sink.events if e.get("event") == "usage_event"]


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(telemetry.AllowlistSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *_a, **_k: provider.get_tracer("t"))
    return exp


async def post(env: Env, key: str, **body: object) -> httpx.Response:
    payload = {"model": "acme-rerank", "query": f"hỏi {CANARY}", "documents": DOCS, **body}
    async with env.gateway_client(key) as c:
        return await c.post("/v1/rerank", json=payload)


# ---------- route ----------


async def test_sorted_desc_top_n_and_usage_event(env: Env) -> None:
    fake = FakeRerankProvider([0.1, 0.9, 0.5, 0.7])
    rerank_env(env, fake)
    key = await env.new_key(allowed_models=("acme-rerank",))
    r = await post(env, key, top_n=2)
    assert r.status_code == 200
    body = r.json()
    assert [x["index"] for x in body["results"]] == [1, 3]
    assert body["results"][0]["relevance_score"] == pytest.approx(0.9)
    assert body["model"] == "acme-rerank"
    assert r.headers["x-acme-provider"] == "fake" and r.headers["x-acme-model"] == "m-rerank"
    assert fake.calls[0][0] == "m-rerank" and fake.calls[0][3] == 2
    (ev,) = usage_events(env)
    assert ev["alias"] == "acme-rerank" and ev["status_code"] == 200 and ev["provider"] == "fake"
    assert ev["output_tokens"] == 0 and ev["key_id"]
    assert CANARY not in json.dumps(ev, default=str)


async def test_top_n_default_all_and_clamped(env: Env) -> None:
    rerank_env(env, FakeRerankProvider([0.4, 0.3, 0.2, 0.1]))
    key = await env.new_key(allowed_models=("acme-rerank",))
    assert len((await post(env, key)).json()["results"]) == 4
    assert len((await post(env, key, top_n=99)).json()["results"]) == 4


async def test_requires_valid_key(env: Env) -> None:
    rerank_env(env, FakeRerankProvider([0.1] * 4))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://gateway"
    ) as c:
        r = await c.post(
            "/v1/rerank", json={"model": "acme-rerank", "query": "q", "documents": ["d"]}
        )
    assert r.status_code == 401
    assert not usage_events(env)


async def test_model_not_allowed(env: Env) -> None:
    fake = FakeRerankProvider([0.1] * 4)
    rerank_env(env, fake)
    key = await env.new_key(allowed_models=("acme-embed",))
    r = await post(env, key)
    assert r.status_code == 403 and r.json()["error"]["code"] == "model_not_allowed"
    assert not fake.calls


async def test_unknown_alias_and_non_rerank_alias(env: Env) -> None:
    rerank_env(env, FakeRerankProvider([0.1] * 4))
    key = await env.new_key(allowed_models=("acme-rerank", "acme-nope"))
    assert (await post(env, key, model="acme-nope")).status_code == 400


@pytest.mark.parametrize(
    "bad",
    [
        {"query": ""},
        {"query": 5},
        {"documents": []},
        {"documents": [""]},
        {"documents": ["a", 1]},
        {"documents": ["a"] * 101},
        {"top_n": 0},
        {"top_n": "2"},
        {"top_n": True},
    ],
)
async def test_invalid_body(env: Env, bad: dict) -> None:
    fake = FakeRerankProvider([0.1] * 4)
    rerank_env(env, fake)
    key = await env.new_key(allowed_models=("acme-rerank",))
    r = await post(env, key, **bad)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert not fake.calls


async def test_provider_error_is_502_and_logged_without_content(env: Env) -> None:
    rerank_env(env, FakeRerankProvider(error=ProviderError("timeout")))
    key = await env.new_key(allowed_models=("acme-rerank",))
    r = await post(env, key)
    assert r.status_code == 502 and r.json()["error"]["code"] == "all_providers_failed"
    (ev,) = usage_events(env)
    assert ev["status_code"] == 502 and ev["error_code"] == "all_providers_failed"
    assert CANARY not in json.dumps(ev, default=str) and CANARY not in r.text


async def test_bad_index_from_provider_is_protocol_error(env: Env) -> None:
    class BadIndex(FakeRerankProvider):
        async def rerank(self, model, query, documents, top_n):
            res = await super().rerank(model, query, documents, top_n)
            res.items[0].index = 99
            return res

    rerank_env(env, BadIndex([0.1] * 4))
    key = await env.new_key(allowed_models=("acme-rerank",))
    assert (await post(env, key)).status_code == 502


async def test_unconfigured_adapter_is_503(env: Env) -> None:
    def boom(_spec):
        raise RerankNotConfigured("x")

    rerank_env(env, FakeRerankProvider([0.1] * 4))
    env.app.state.container.rerank._providers = boom
    key = await env.new_key(allowed_models=("acme-rerank",))
    r = await post(env, key)
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"


async def test_span_has_counts_not_content(env: Env, spans: InMemorySpanExporter) -> None:
    rerank_env(env, FakeRerankProvider([0.1, 0.9, 0.5, 0.7]))
    key = await env.new_key(allowed_models=("acme-rerank",))
    assert (await post(env, key, top_n=2)).status_code == 200
    (s,) = [x for x in spans.get_finished_spans() if x.name == "gen_ai.rerank"]
    a = dict(s.attributes)
    assert a["candidates"] == 4 and a["returned"] == 2 and a["gen_ai.request.model"] == "m-rerank"
    assert CANARY not in s.to_json()


# ---------- adapter http_rerank (httpx.MockTransport, không mạng) ----------


def adapter(handler, *, api_key: str | None = None, base_url: str = "http://rerank.test:8081"):
    http = RetryingHttpClient(transport=httpx.MockTransport(handler), max_attempts=1)
    return HttpRerankProvider(base_url=base_url, api_key=api_key, http=http)


def replying(status: int = 200, **kw):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, **kw)

    return handler, seen


async def test_adapter_request_and_response_shape() -> None:
    handler, seen = replying(
        json={
            "results": [{"index": 1, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.2}],
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        }
    )
    p = adapter(handler)
    assert isinstance(p, RerankProvider)
    res = await p.rerank("bge", "q", ["a", "b"], 2)
    assert [(i.index, i.score) for i in res.items] == [(1, 0.8), (0, 0.2)]
    assert res.prompt_tokens == 7
    assert str(seen[0].url) == "http://rerank.test:8081/v1/rerank"
    assert json.loads(seen[0].content) == {
        "model": "bge",
        "query": "q",
        "documents": ["a", "b"],
        "top_n": 2,
    }
    assert "authorization" not in seen[0].headers


async def test_adapter_sends_bearer_when_key_set() -> None:
    handler, seen = replying(json={"results": []})
    await adapter(handler, api_key="k-secret", base_url="http://h:1/").rerank("m", "q", ["a"], 1)
    assert seen[0].headers["authorization"] == "Bearer k-secret"
    assert str(seen[0].url) == "http://h:1/v1/rerank"


@pytest.mark.parametrize("status", [400, 404, 500])
async def test_adapter_http_error_has_no_url(status: int) -> None:
    handler, _ = replying(status, text="x")
    with pytest.raises(ProviderError) as e:
        await adapter(handler).rerank("m", "q", ["a"], 1)
    assert "rerank.test" not in str(e.value)


@pytest.mark.parametrize(
    "body", [{"nope": 1}, {"results": [{"index": "x", "relevance_score": 1}]}, {"results": 5}]
)
async def test_adapter_protocol_error(body: dict) -> None:
    handler, _ = replying(json=body)
    with pytest.raises(ProviderError, match="protocol"):
        await adapter(handler).rerank("m", "q", ["a"], 1)


async def test_adapter_timeout_maps_to_provider_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("t")

    with pytest.raises(ProviderError, match="timeout"):
        await adapter(handler).rerank("m", "q", ["a"], 1)


# ---------- factory + catalog ----------


def test_factory_builds_known_and_rejects_unknown() -> None:
    s = make_settings()
    p = build_rerank_provider("http_rerank", s, {"base_url": "http://h:8081", "path": "/rerank"})
    assert isinstance(p, HttpRerankProvider) and p._url == "http://h:8081/rerank"
    with pytest.raises(RerankNotConfigured, match="known: "):
        build_rerank_provider("nope", s)
    with pytest.raises(RerankNotConfigured, match="base_url"):
        build_rerank_provider("http_rerank", s, {})


def test_catalog_rerank_spec_and_real_config() -> None:
    from pathlib import Path

    import gateway

    cfg = Path(gateway.__file__).resolve().parents[2] / "config"
    real = ModelCatalog.from_file(cfg / "models.yaml")
    spec = real.rerank("acme-rerank")
    assert spec.adapter == "http_rerank"
    assert spec.options["base_url"] == "https://openrouter.ai/api"
    default = ModelCatalog.from_file(Path(__file__).resolve().parent / "models.test.yaml")
    assert "acme-rerank" not in default.aliases()
    with pytest.raises(GatewayError):
        real.rerank("acme-embed")


# ---------- CLI update-key-models ----------


async def test_update_key_models(env: Env, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    key = await env.new_key(allowed_models=("acme-embed",))
    rec = env.keys.records[parse_key(key)[0]]  # type: ignore[index]
    sink = FakeEventSink()
    monkeypatch.setattr("sys.stdin", io.StringIO(key + "\n"))
    args = parser().parse_args(
        ["--actor", "boot", "update-key-models", "--allowed-models", "acme-embed, acme-rerank"]
    )
    assert await update_key_models(args, env.keys, sink, FakeClock(), env.settings) == 0
    assert env.keys.records[rec.prefix].allowed_models == ("acme-embed", "acme-rerank")
    out = capsys.readouterr()
    assert key not in out.out and key not in out.err
    (audit,) = sink.events
    assert audit["action"] == "key.update_models" and key not in str(audit)
    assert audit["details"]["after"] == ["acme-embed", "acme-rerank"]


async def test_update_key_models_rejects_bad_key(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    key = await env.new_key()
    args = parser().parse_args(["update-key-models", "--allowed-models", "acme-rerank"])
    other = "sk-acme-" + "A" * 12 + "." + "b" * 43
    for bad in (other, "rac"):
        monkeypatch.setattr("sys.stdin", io.StringIO(bad))
        code = await update_key_models(args, env.keys, FakeEventSink(), FakeClock(), env.settings)
        assert code == 3
    # key bị thu hồi
    rec = env.keys.records[parse_key(key)[0]]  # type: ignore[index]
    await env.keys.revoke(rec.key_id, "t", "x")
    monkeypatch.setattr("sys.stdin", io.StringIO(key))
    assert await update_key_models(args, env.keys, FakeEventSink(), FakeClock(), env.settings) == 3


async def test_update_key_models_rejects_empty_list(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = await env.new_key()
    monkeypatch.setattr("sys.stdin", io.StringIO(key))
    args = parser().parse_args(["update-key-models", "--allowed-models", " , "])
    assert await update_key_models(args, env.keys, FakeEventSink(), FakeClock(), env.settings) == 2


async def test_fake_key_store_update_unknown_raises() -> None:
    from gateway.ports import KeyNotFound

    with pytest.raises(KeyNotFound):
        await FakeKeyStore().update_allowed_models("nope", ("a",), "t")
