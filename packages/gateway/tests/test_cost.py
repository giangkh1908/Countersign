"""Chi phí thật trong `usage_events.cost_micro_usd`: provider báo > bảng giá theo alias > 0; cache hit = 0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from acme_common.http import RetryingHttpClient
from acme_common.ports import Principal
from acme_common.testing import FakeClock, FakeEventSink, FakeTokenVerifier
from gateway.adapters.http_rerank import HttpRerankProvider
from gateway.adapters.openai_chat import OpenAIChatProvider
from gateway.adapters.openai_compatible import OpenAICompatibleEmbeddingProvider
from gateway.container import build_container
from gateway.main import create_app
from gateway.ports.types import ChatChunk, ChatRequest, ChatResponse, Usage
from gateway.services.catalog import ModelCatalog, Price
from gateway.services.errors import GatewayError
from gateway.services.key_admin import issue_key
from gateway.services.pricing import cost_usd, to_micro_usd
from gateway.testing import (
    FakeChatProvider,
    FakeEmbeddingProvider,
    FakeKeyStore,
    FakeRerankProvider,
    FakeResponseCache,
    provider_lookup,
)
from gw_support import PEPPER, make_settings

USER = Principal(
    sub="u",
    audience=("llm-gateway",),
    azp="chat-ui",
    scopes=frozenset(),
    expires_at=2e9,
    dept=("IT",),
    clearance=1,
    roles=("staff",),
)
MSG = [{"role": "user", "content": "hi"}]
CONFIG = """\
aliases:
  priced: { chain: [mock/m], price: { input_per_mtok: 2.0, output_per_mtok: 4.0 } }
  free: { chain: [mock/m] }
  emb:
    kind: embedding
    adapter: openai_compatible
    model: m-emb
    dim: 2
    price: { input_per_mtok: 100 }
  rr:
    kind: rerank
    adapter: http_rerank
    model: m-rr
    price: { input_per_mtok: 3.0 }
"""


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        chat: FakeChatProvider,
        emb: FakeEmbeddingProvider | None = None,
        rr: FakeRerankProvider | None = None,
        cache: FakeResponseCache | None = None,
    ) -> None:
        cfg = tmp_path / "models.yaml"
        cfg.write_text(CONFIG, encoding="utf8")
        self.sink, self.keys = FakeEventSink(), FakeKeyStore()
        settings = make_settings(gw_models_config=str(cfg))
        container = build_container(
            settings,
            clock=FakeClock(),
            keys=self.keys,
            verifier=FakeTokenVerifier({"t-it": USER}),
            sink=self.sink,
            providers=provider_lookup(mock=chat),
            embedders=lambda _s: emb or FakeEmbeddingProvider([[1.0, 0.0]]),
            rerankers=lambda _s: rr or FakeRerankProvider([0.5, 0.1]),
            cache=cache,
        )
        self.app = create_app(settings, container)

    async def client(self) -> httpx.AsyncClient:
        issued = issue_key(
            PEPPER.encode(),
            name="t",
            owner_type="service",
            owner_ref="t",
            dept="IT",
            allowed_models=("priced", "free", "emb", "rr"),
            rpm=60,
            tpm=100_000,
            trust_end_user_token=True,
        )
        await self.keys.create(issued.new, "t")
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://gw",
            headers={"authorization": f"Bearer {issued.plaintext}", "x-acme-user-token": "t-it"},
        )

    def costs(self) -> list[int]:
        return [e["cost_micro_usd"] for e in self.sink.events if e.get("event") == "usage_event"]


def chat_provider(usage: Usage) -> FakeChatProvider:
    reply = ChatResponse({"role": "assistant", "content": "ok"}, "stop", usage, "m", "fake")
    chunks = [ChatChunk(text="ok"), ChatChunk(finish_reason="stop", usage=usage)]
    return FakeChatProvider(response=reply, chunks=chunks)


async def chat(c: httpx.AsyncClient, model: str, **extra: Any) -> httpx.Response:
    return await c.post("/v1/chat/completions", json={"model": model, "messages": MSG, **extra})


# ---------- hàm thuần ----------


def test_cost_usd_priority_and_rounding() -> None:
    price = Price(2.0, 4.0)
    assert cost_usd(0.5, price, 10, 5) == 0.5  # provider báo thắng bảng giá
    assert cost_usd(0.0, price, 10, 5) == 0.0  # báo 0 vẫn là báo
    assert cost_usd(None, price, 10, 5) == pytest.approx(40e-6)
    assert cost_usd(None, None, 10, 5) == 0.0
    assert to_micro_usd(8.25e-7) == 1 and to_micro_usd(4.9e-7) == 0 and to_micro_usd(-1.0) == 0


# ---------- chat ----------


async def test_reported_cost_wins_over_price_table(tmp_path: Path) -> None:
    rig = Rig(tmp_path, chat_provider(Usage(10, 5, cost_usd=0.000123)))
    async with await rig.client() as c:
        r = await chat(c, "priced")
    assert rig.costs() == [123]
    assert r.headers["x-acme-cost-usd"] == "0.00012300"


async def test_price_table_fallback_when_not_reported(tmp_path: Path) -> None:
    rig = Rig(tmp_path, chat_provider(Usage(10, 5)))
    async with await rig.client() as c:
        r = await chat(c, "priced")
    assert rig.costs() == [40]  # (10*2 + 5*4) / 1e6 USD
    assert r.headers["x-acme-cost-usd"] == "0.00004000"


async def test_no_price_no_report_is_zero(tmp_path: Path) -> None:
    rig = Rig(tmp_path, chat_provider(Usage(10, 5)))
    async with await rig.client() as c:
        await chat(c, "free")
    assert rig.costs() == [0]


async def test_stream_takes_cost_from_final_usage_chunk(tmp_path: Path) -> None:
    rig = Rig(tmp_path, chat_provider(Usage(10, 5, cost_usd=0.0002)))
    async with await rig.client() as c:
        r = await chat(c, "priced", stream=True, stream_options={"include_usage": True})
    assert rig.costs() == [200]
    final = [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: {")][-1]
    assert final["x_acme"]["cost_usd"] == pytest.approx(0.0002)


async def test_stream_price_table_fallback(tmp_path: Path) -> None:
    rig = Rig(tmp_path, chat_provider(Usage(10, 5)))
    async with await rig.client() as c:
        await chat(c, "priced", stream=True)
    assert rig.costs() == [40]


@pytest.mark.parametrize("stream", [False, True])
async def test_cache_hit_costs_zero(tmp_path: Path, stream: bool) -> None:
    rig = Rig(tmp_path, chat_provider(Usage(10, 5, cost_usd=0.0002)), cache=FakeResponseCache())
    async with await rig.client() as c:
        await chat(c, "priced", stream=stream)
        r = await chat(c, "priced", stream=stream)
    assert r.headers["x-acme-cache"] == "exact"
    assert rig.costs() == [200, 0]


# ---------- embeddings / rerank ----------


async def test_embeddings_reported_and_table(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path, chat_provider(Usage()), emb=FakeEmbeddingProvider([[1.0, 0.0]], cost_usd=7e-6)
    )
    async with await rig.client() as c:
        assert (
            await c.post("/v1/embeddings", json={"model": "emb", "input": "a"})
        ).status_code == 200
    assert rig.costs() == [7]
    rig = Rig(tmp_path, chat_provider(Usage()), emb=FakeEmbeddingProvider([[1.0, 0.0]]))
    async with await rig.client() as c:
        await c.post("/v1/embeddings", json={"model": "emb", "input": "a"})
    assert rig.costs() == [100]  # 1 token * 100 USD/Mtok


async def test_rerank_reported_and_table(tmp_path: Path) -> None:
    body = {"model": "rr", "query": "abcd", "documents": ["x", "y"]}
    rig = Rig(tmp_path, chat_provider(Usage()), rr=FakeRerankProvider([0.5, 0.1], cost_usd=3e-5))
    async with await rig.client() as c:
        assert (await c.post("/v1/rerank", json=body)).status_code == 200
    assert rig.costs() == [30]
    rig = Rig(tmp_path, chat_provider(Usage()), rr=FakeRerankProvider([0.5, 0.1]))
    async with await rig.client() as c:
        await c.post("/v1/rerank", json=body)
    assert rig.costs() == [12]  # 4 token (len(query) của fake) * 3 USD/Mtok


# ---------- adapter đọc usage.cost ----------


async def test_chat_adapter_reads_usage_cost_non_stream_and_stream() -> None:
    usage = {"prompt_tokens": 5, "completion_tokens": 5, "cost": 8.25e-7, "is_byok": False}
    sse_body = (
        'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
        'data: {"choices":[],"usage":' + json.dumps(usage) + "}\n\n"
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["stream"]:
            return httpx.Response(200, text=sse_body)
        msg = {"role": "assistant", "content": "hi"}
        return httpx.Response(
            200, json={"choices": [{"message": msg, "finish_reason": "stop"}], "usage": usage}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    p = OpenAIChatProvider("http://x", client=client)
    req = ChatRequest(alias="a", model="m", messages=MSG)
    assert (await p.complete(req)).usage.cost_usd == 8.25e-7
    req.stream = True
    last = [ch async for ch in p.stream(req) if ch.usage is not None][-1]
    assert last.usage is not None and last.usage.cost_usd == 8.25e-7


async def test_chat_adapter_without_cost_is_none() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        msg = {"role": "assistant", "content": "hi"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": msg, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": "x"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    p = OpenAIChatProvider("http://x", client=client)
    assert (
        await p.complete(ChatRequest(alias="a", model="m", messages=MSG))
    ).usage.cost_usd is None


async def test_embedding_and_rerank_adapters_read_usage_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            data = [{"index": 0, "embedding": [0.1, 0.2]}]
            return httpx.Response(
                200, json={"data": data, "usage": {"prompt_tokens": 4, "cost": 4e-8}}
            )
        results = [{"index": 0, "relevance_score": 0.3}]
        return httpx.Response(
            200, json={"results": results, "usage": {"total_tokens": 151, "cost": 3.02e-5}}
        )

    def http() -> RetryingHttpClient:
        return RetryingHttpClient(transport=httpx.MockTransport(handler), max_attempts=1)

    emb = OpenAICompatibleEmbeddingProvider(base_url="http://x/v1", api_key=None, http=http())
    assert (await emb.embed("m", ["a"])).cost_usd == 4e-8
    rr = HttpRerankProvider(base_url="http://x", api_key=None, http=http())
    assert (await rr.rerank("m", "q", ["a"], 1)).cost_usd == 3.02e-5


# ---------- catalog ----------


def test_catalog_reads_price() -> None:
    cat = ModelCatalog.from_file(_cfg())
    assert cat.resolve("priced").price == Price(2.0, 4.0)
    assert cat.resolve("free").price is None
    assert cat.embedding("emb").price == Price(100.0, 0.0)
    assert "price" not in cat.embedding("emb").options
    assert cat.rerank("rr").price == Price(3.0, 0.0)


def _cfg() -> Path:
    import tempfile

    p = Path(tempfile.mkdtemp()) / "m.yaml"
    p.write_text(CONFIG, encoding="utf8")
    return p


@pytest.mark.parametrize(
    "bad",
    [
        [1, 2],
        "x",
        {"input_per_mtok": -1},
        {"input_per_mtok": "1"},
        {"input_per_mtok": True},
        {"output_per_mtok": float("nan")},
        {"unknown": 1},
    ],
)
def test_catalog_rejects_bad_price(bad: Any) -> None:
    cat = ModelCatalog({"aliases": {"a": {"chain": ["mock/m"], "price": bad}}})
    with pytest.raises(GatewayError):
        cat.resolve("a")


def test_shipped_aliases_have_prices() -> None:
    cat = ModelCatalog.from_file(Path(__file__).resolve().parents[1] / "config" / "models.yaml")
    for alias in ("acme-fast", "acme-smart", "acme-judge"):
        assert cat.resolve(alias).price is not None
    assert cat.embedding("acme-embed").price is not None
    assert cat.rerank("acme-rerank").price is not None
