"""Rerank trong docs-mcp: adapter `gateway_rerank` (MockTransport), `DocumentService` (top_n, cờ, suy giảm), factory."""

from __future__ import annotations

import json

import fakeredis.aioredis
import httpx
import pytest
from acme_common.http import RetryingHttpClient
from acme_common.mcp import CallerContext
from acme_common.ports import Principal
from mcp_docs import factory
from mcp_docs.adapters.gateway_rerank import GatewayRerankReranker
from mcp_docs.adapters.none import NoReranker
from mcp_docs.ports import Reranker, RerankUnavailable
from mcp_docs.services.document_service import DocumentService
from mcp_docs.settings import Settings
from mcp_docs.testing import FakeReranker, FakeRetriever, make_chunk


def ctx() -> CallerContext:
    p = Principal(
        sub="u1",
        audience=("docs-mcp",),
        azp="agent-service",
        scopes=frozenset({"docs:read"}),
        expires_at=1e12,
        dept=("HR",),
        clearance=1,
        roles=("employee",),
    )
    return CallerContext(principal=p, request_id="r", thread_id="t1")


# ---------- adapter gateway_rerank ----------


def adapter(handler, **kw) -> GatewayRerankReranker:
    http = RetryingHttpClient(transport=httpx.MockTransport(handler), max_attempts=1)
    return GatewayRerankReranker(base_url="http://gw/v1/", api_key="k-secret", http=http, **kw)


CHUNKS = [make_chunk(i, "ALL", 0, content=f"nội dung {i}") for i in (1, 2, 3)]


async def test_request_shape_and_reorder_with_scores() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        res = [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.4},
               {"index": 1, "relevance_score": 0.1}]  # fmt: skip
        return httpx.Response(200, json={"results": res})

    r = adapter(handler)
    assert isinstance(r, Reranker) and r.active
    out = await r.rerank("câu hỏi", CHUNKS)
    assert [c.chunk_id for c in out] == [3, 1, 2]
    assert [c.score for c in out] == [0.9, 0.4, 0.1]
    assert seen["url"] == "http://gw/v1/rerank" and seen["auth"] == "Bearer k-secret"
    assert seen["body"] == {
        "model": "acme-rerank",
        "query": "câu hỏi",
        "documents": ["nội dung 1", "nội dung 2", "nội dung 3"],
        "top_n": 3,
    }


async def test_missing_indices_keep_old_order_at_the_end() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.5}]})

    out = await adapter(handler).rerank("q", CHUNKS)
    assert [c.chunk_id for c in out] == [2, 1, 3]


async def test_fewer_than_two_chunks_skips_call() -> None:
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("không được gọi")

    assert await adapter(handler).rerank("q", CHUNKS[:1]) == CHUNKS[:1]
    assert await adapter(handler).rerank("q", []) == []


@pytest.mark.parametrize("status", [401, 404, 502])
async def test_http_status_maps_to_unavailable(status: int) -> None:
    with pytest.raises(RerankUnavailable) as e:
        await adapter(lambda r: httpx.Response(status)).rerank("q", CHUNKS)
    assert e.value.kind == f"http_{status}" and "gw" not in str(e.value)


@pytest.mark.parametrize(
    "body",
    [
        {"x": 1},
        {"results": [{"index": 0}]},
        {"results": [{"index": 5, "relevance_score": 1}]},
        {"results": [{"index": 0, "relevance_score": 1}, {"index": 0, "relevance_score": 2}]},
    ],
)
async def test_bad_body_maps_to_unavailable(body: dict) -> None:
    with pytest.raises(RerankUnavailable):
        await adapter(lambda r: httpx.Response(200, json=body)).rerank("q", CHUNKS)


async def test_timeout_maps_to_unavailable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("t")

    with pytest.raises(RerankUnavailable) as e:
        await adapter(handler).rerank("q", CHUNKS)
    assert e.value.kind == "timeout"


# ---------- DocumentService ----------

STORE = [make_chunk(i, "ALL", 0, content=f"nội dung {i}") for i in range(1, 7)]


def service(reranker: Reranker, top_n: int = 3, *, retriever: FakeRetriever | None = None):
    return DocumentService(
        retriever or FakeRetriever(list(STORE)),
        reranker,
        redis=fakeredis.aioredis.FakeRedis(),
        max_per_doc=2,
        rerank_top_n=top_n,
    )


def ids(out: dict) -> list[int]:
    return [r["chunk_id"] for r in out["results"]]


async def test_none_reranker_reports_false_and_keeps_order() -> None:
    out, _ = await service(NoReranker()).search(ctx(), "lương", top_k=6)
    assert out["reranked"] is False and out["mode"] == "hybrid" and ids(out) == [1, 2, 3, 4, 5, 6]


async def test_only_top_n_head_is_reranked_tail_stays_behind() -> None:
    fake = FakeReranker(
        {3: 9.0, 2: 5.0, 1: 1.0, 6: 100.0}
    )  # 6 nằm ngoài top_n: không được vượt lên
    out, _ = await service(fake, top_n=3).search(ctx(), "lương", top_k=6)
    assert fake.calls[0][1] == [1, 2, 3]
    assert ids(out) == [3, 2, 1, 4, 5, 6]
    assert out["reranked"] is True and out["mode"] == "hybrid"


async def test_retriever_asked_for_at_least_top_n_when_active() -> None:
    retr = FakeRetriever(list(STORE))
    await service(FakeReranker(), top_n=30, retriever=retr).search(ctx(), "q", top_k=1)
    assert retr.calls[0][1] == 30
    retr2 = FakeRetriever(list(STORE))
    await service(NoReranker(), top_n=30, retriever=retr2).search(ctx(), "q", top_k=1)
    assert retr2.calls[0][1] == 6  # top_k * max_per_doc + 4


async def test_rerank_failure_degrades_with_rerank_skipped() -> None:
    out, audit = await service(FakeReranker(fail=True)).search(ctx(), "lương", top_k=6)
    assert ids(out) == [1, 2, 3, 4, 5, 6]  # thứ tự RRF còn nguyên
    assert out["reranked"] is False
    assert out["mode"] == "hybrid+rerank_skipped" and audit["mode"] == out["mode"]


async def test_rerank_never_resurrects_unauthorized_chunk() -> None:
    """Fake retriever rò (enforce_acl=False): ACL kiểm lại sau rerank vẫn loại chunk trái quyền."""
    store = [make_chunk(1, "ALL", 0), make_chunk(2, "HR", 3, ("dept_manager",))]
    retr = FakeRetriever(store, enforce_acl=False)
    out, _ = await service(FakeReranker({2: 9.0}), retriever=retr).search(ctx(), "q", top_k=5)
    assert ids(out) == [1] and out["reranked"] is True


# ---------- factory + settings ----------


def test_factory_builds_gateway_rerank_and_default_none() -> None:
    s = Settings()
    assert s.docs_rerank == "none" and s.docs_rerank_top_n == 30
    assert isinstance(factory.build_reranker("none", s), NoReranker)
    r = factory.build_reranker("gateway_rerank", s)
    assert isinstance(r, GatewayRerankReranker) and isinstance(r, Reranker)
    assert r._url == "http://gateway:8000/v1/rerank" and r._model == "acme-rerank"


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_RERANK", "gateway_rerank")
    monkeypatch.setenv("DOCS_RERANK_TOP_N", "12")
    s = Settings()
    assert s.docs_rerank == "gateway_rerank" and s.docs_rerank_top_n == 12
