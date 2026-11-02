"""`POST /v1/embeddings`: hợp đồng qua SDK `openai`, adapter `mock_hash` và `openai_compatible`, factory."""

from __future__ import annotations

import json
import math

import httpx
import openai
import pytest
from acme_common.http import RetryingHttpClient
from gateway.adapters.mock_hash import MockHashEmbeddingProvider
from gateway.adapters.openai_compatible import OpenAICompatibleEmbeddingProvider
from gateway.container import build_container
from gateway.factory import build_embedding_provider
from gateway.main import create_app
from gateway.ports import EmbeddingNotConfigured, EmbeddingProvider, ProviderError
from gateway.testing import FakeEmbeddingProvider
from gw_support import Env, make_settings

SECRET = "sk-embed-secret-123"


def sdk(env: Env, key: str) -> openai.AsyncOpenAI:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app))
    return openai.AsyncOpenAI(
        base_url="http://gateway/v1", api_key=key, http_client=http, max_retries=0
    )


def usage_events(env: Env) -> list[dict]:
    return [e for e in env.sink.events if e.get("event") == "usage_event"]


# ---------- route qua SDK openai ----------


async def test_single_string_and_shape(env: Env, api_key: str) -> None:
    raw = await sdk(env, api_key).embeddings.with_raw_response.create(
        model="acme-embed", input="điều 5 luật lao động"
    )
    r = raw.parse()
    assert r.model == "acme-embed" and r.object == "list"
    assert len(r.data) == 1 and r.data[0].index == 0 and len(r.data[0].embedding) == 1024
    assert math.isclose(sum(x * x for x in r.data[0].embedding), 1.0, rel_tol=1e-6)
    assert r.usage.prompt_tokens == r.usage.total_tokens == 5
    assert raw.headers["x-acme-provider"] == "mock_hash"
    assert raw.headers["x-acme-model"] == "mock-hash-1024"


async def test_float_format_matches_default_base64(env: Env, api_key: str) -> None:
    client = sdk(env, api_key)
    f = await client.embeddings.create(model="acme-embed", input="a b c", encoding_format="float")
    b = await client.embeddings.create(model="acme-embed", input="a b c")  # SDK gửi base64
    assert f.data[0].embedding == pytest.approx(b.data[0].embedding, abs=1e-6)
    async with env.gateway_client(api_key) as c:
        r = await c.post(
            "/v1/embeddings", json={"model": "acme-embed", "input": "x", "encoding_format": "int8"}
        )
    assert r.status_code == 400


async def test_batch_keeps_index_order(env: Env, api_key: str) -> None:
    texts = [f"văn bản số {i}" for i in range(32)]
    client = sdk(env, api_key)
    r = await client.embeddings.create(model="acme-embed", input=texts)
    assert [d.index for d in r.data] == list(range(32))
    singles = [(await client.embeddings.create(model="acme-embed", input=t)).data[0] for t in texts]
    assert [d.embedding for d in r.data] == [s.embedding for s in singles]


async def test_more_than_32_inputs_rejected(env: Env, api_key: str) -> None:
    with pytest.raises(openai.BadRequestError) as e:
        await sdk(env, api_key).embeddings.create(
            model="acme-embed", input=[f"t{i}" for i in range(33)]
        )
    assert e.value.body["code"] == "invalid_request"  # type: ignore[index]


@pytest.mark.parametrize("bad", [[], "", [""], [[1, 2, 3]], 5])
async def test_invalid_input_rejected(env: Env, api_key: str, bad: object) -> None:
    async with env.gateway_client(api_key) as c:
        r = await c.post("/v1/embeddings", json={"model": "acme-embed", "input": bad})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


async def test_model_not_allowed(env: Env) -> None:
    key = await env.new_key(allowed_models=("acme-fast",))
    with pytest.raises(openai.PermissionDeniedError) as e:
        await sdk(env, key).embeddings.create(model="acme-embed", input="x")
    assert e.value.body["code"] == "model_not_allowed"  # type: ignore[index]
    assert not any(e["status_code"] == 200 for e in usage_events(env))


async def test_chat_alias_is_not_an_embedding_model(env: Env, api_key: str) -> None:
    with pytest.raises(openai.BadRequestError):
        await sdk(env, api_key).embeddings.create(model="acme-fast", input="x")


async def test_requires_auth(env: Env) -> None:
    with pytest.raises(openai.AuthenticationError):
        await sdk(env, "acme-sk-nope").embeddings.create(model="acme-embed", input="x")


async def test_usage_event_and_client_request_id(env: Env, api_key: str) -> None:
    async with env.gateway_client(api_key, **{"X-Acme-Client-Request-Id": "cli-1"}) as c:
        r = await c.post(
            "/v1/embeddings", json={"model": "acme-embed", "input": ["alpha beta", "gamma"]}
        )
    assert r.status_code == 200
    assert r.headers["x-acme-client-request-id"] == "cli-1"
    (ev,) = usage_events(env)
    assert ev["request_id"] == r.headers["x-acme-request-id"]
    assert ev["alias"] == "acme-embed" and ev["provider"] == "mock_hash"
    assert ev["model"] == "mock-hash-1024" and ev["input_tokens"] == 3
    assert ev["output_tokens"] == 0 and ev["status_code"] == 200 and ev["error_code"] is None
    assert "alpha" not in json.dumps(ev, default=str)  # không ghi nội dung


def _app_with(env: Env, fake: EmbeddingProvider) -> None:
    c = build_container(
        env.settings, clock=env.clock, keys=env.keys, verifier=env.verifier, sink=env.sink,
        providers=env.providers, embedders=lambda spec: fake,
    )  # fmt: skip
    env.app = create_app(env.settings, c)


async def test_provider_error_maps_to_502_and_records_event(env: Env, api_key: str) -> None:
    _app_with(env, FakeEmbeddingProvider(error=ProviderError("timeout", retryable=True)))
    with pytest.raises(openai.InternalServerError) as e:
        await sdk(env, api_key).embeddings.create(model="acme-embed", input="x")
    assert e.value.status_code == 502
    (ev,) = usage_events(env)
    assert ev["status_code"] == 502 and ev["error_code"] == "all_providers_failed"


async def test_wrong_dimension_from_provider_is_502(env: Env, api_key: str) -> None:
    _app_with(env, FakeEmbeddingProvider(vectors=[[1.0, 0.0]]))
    with pytest.raises(openai.InternalServerError):
        await sdk(env, api_key).embeddings.create(model="acme-embed", input="x")


# ---------- adapter ----------


async def test_mock_hash_is_deterministic_and_normalized() -> None:
    p = MockHashEmbeddingProvider(dim=64)
    a = await p.embed("m", ["Xin chào thế giới", "khác hẳn"])
    b = await MockHashEmbeddingProvider(dim=64).embed("other-model", ["Xin chào thế giới"])
    assert a.vectors[0] == b.vectors[0] != a.vectors[1]
    assert all(len(v) == 64 for v in a.vectors)
    assert all(math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-9) for v in a.vectors)
    assert a.prompt_tokens == 6


async def test_mock_hash_shared_tokens_are_closer() -> None:
    r = await MockHashEmbeddingProvider(dim=256).embed(
        "m", ["hợp đồng lao động", "hợp đồng thuê nhà", "bóng đá hôm nay"]
    )
    dot = lambda x, y: sum(i * j for i, j in zip(x, y, strict=True))  # noqa: E731
    assert dot(r.vectors[0], r.vectors[1]) > dot(r.vectors[0], r.vectors[2])


def _oc(
    handler: httpx.MockTransport | None = None, **kw: object
) -> OpenAICompatibleEmbeddingProvider:
    http = RetryingHttpClient(transport=handler, max_attempts=1)
    return OpenAICompatibleEmbeddingProvider(
        base_url="https://embed.example/v1/",
        api_key=SECRET,
        http=http,
        **kw,  # type: ignore[arg-type]
    )


async def test_openai_compatible_request_and_parse() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = (
            str(req.url),
            req.headers["authorization"],
            req.read(),
        )
        return httpx.Response(
            200,
            json={
                "data": [  # cố tình đảo thứ tự
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
        )

    p = _oc(httpx.MockTransport(handler))
    res = await p.embed("real-model", ["a", "b"])
    assert res.vectors == [[1.0, 0.0], [0.0, 1.0]] and res.prompt_tokens == 7
    assert seen["url"] == "https://embed.example/v1/embeddings"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert json.loads(seen["body"]) == {
        "model": "real-model", "input": ["a", "b"], "encoding_format": "float",
    }  # fmt: skip
    await p.aclose()


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(401, text=f"bad key {SECRET}"),
        httpx.Response(500, text=f"boom {SECRET}"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]}),  # thiếu phần tử
    ],
)
async def test_openai_compatible_errors_do_not_leak_key(resp: httpx.Response) -> None:
    p = _oc(httpx.MockTransport(lambda _: resp))
    with pytest.raises(ProviderError) as e:
        await p.embed("m", ["a", "b"])
    assert SECRET not in str(e.value) and "embed.example" not in str(e.value)


async def test_openai_compatible_transport_error_has_no_url() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot reach https://embed.example")

    with pytest.raises(ProviderError) as e:
        await _oc(httpx.MockTransport(boom)).embed("m", ["a"])
    assert e.value.kind == "connection" and e.value.retryable
    assert "embed.example" not in str(e.value)


# ---------- factory ----------


def test_factory_known_names() -> None:
    s = make_settings(gw_embedding_api_key=SECRET)
    p = build_embedding_provider("mock_hash", s, {"dim": 8})
    assert isinstance(p, EmbeddingProvider) and isinstance(p, MockHashEmbeddingProvider)
    q = build_embedding_provider("openai_compatible", s, {"base_url": "https://x/v1"})
    assert isinstance(q, EmbeddingProvider) and isinstance(q, OpenAICompatibleEmbeddingProvider)


def test_factory_unknown_and_missing_base_url() -> None:
    with pytest.raises(EmbeddingNotConfigured) as e:
        build_embedding_provider("nope", make_settings())
    assert "mock_hash" in str(e.value) and "openai_compatible" in str(e.value)
    with pytest.raises(EmbeddingNotConfigured, match="base_url"):
        build_embedding_provider("openai_compatible", make_settings(), {})
