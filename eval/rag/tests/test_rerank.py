"""Cấu hình `vector_rerank` / `hybrid_rerank` của harness: ghi đè Settings, decorator, độ trễ rerank."""

from __future__ import annotations

from pathlib import Path

import pytest
from acme_common.ports import Principal
from mcp_docs.adapters.gateway_rerank import GatewayRerankReranker
from mcp_docs.ports import DocumentRetriever, RetrievedChunk, SearchResult
from mcp_docs.settings import Settings
from mcp_docs.testing import FakeReranker

from eval.rag import backends, runner
from eval.rag.dataset import Question
from eval.rag.fakes import eval_principal


def _chunk(i: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=i, doc_id="d", title="d", heading=None, source=f"d#{i}", ord=i,
        department="ALL", classification=0, allowed_roles=(), content="x", doc_num="d",
        article=str(i),
    )  # fmt: skip


class Inner(DocumentRetriever):
    def __init__(self, n: int = 8) -> None:
        self.n = n
        self.ks: list[int] = []
        self.closed = False

    async def search(
        self, query: str, principal: Principal, k: int, department_filter: str | None = None
    ) -> SearchResult:
        self.ks.append(k)
        return SearchResult([_chunk(i) for i in range(1, self.n + 1)][:k], "hybrid")

    async def aclose(self) -> None:
        self.closed = True


def test_overrides_vector_and_hybrid_rerank_with_top_n():
    o = backends.config_overrides("vector_rerank@top10")
    assert o["docs_rerank"] == "gateway_rerank" and o["docs_rerank_top_n"] == 10
    assert o["docs_use_vector"] is True and o["docs_use_fts"] is False
    o = backends.config_overrides("hybrid_rerank")
    assert o["docs_use_fts"] is True and "docs_rerank_top_n" not in o  # lấy mặc định Settings
    assert "docs_rerank" not in backends.config_overrides("hybrid")  # nền không rerank
    for name in backends.GROUPS["rerank"]:
        backends.config_overrides(name)


def test_every_override_key_is_a_real_setting():
    fields = set(Settings.model_fields)
    for name in backends.GROUPS["rerank"]:
        assert set(backends.config_overrides(name)) <= fields


def test_real_factory_builds_decorator_via_settings_override(monkeypatch: pytest.MonkeyPatch):
    class Built(Inner):
        pass

    monkeypatch.setattr(backends, "build_embedder", lambda *_: object())
    monkeypatch.setattr(backends, "build_retriever", lambda *_a, **_k: Built())
    cfgs = ("hybrid", "vector_rerank@top10")
    build = backends.real_factory(Settings(docs_gateway_key="k-test"), cfgs)
    plain = build("hybrid")
    assert isinstance(plain, Built)  # không rerank => không bọc
    rr = build("vector_rerank@top10")
    assert isinstance(rr, backends.RerankingRetriever)
    assert rr._top_n == 10 and isinstance(rr._reranker, GatewayRerankReranker)


async def test_decorator_reranks_head_keeps_tail_and_asks_enough_candidates():
    inner = Inner(8)
    fake = FakeReranker({3: 9.0, 2: 5.0, 1: 1.0, 7: 99.0})
    r = backends.RerankingRetriever(inner, fake, top_n=3)
    res = await r.search("q", eval_principal(), 2)
    assert inner.ks == [3]  # max(k, top_n)
    assert [c.chunk_id for c in res.chunks] == [3, 2]
    assert res.mode == "hybrid" and r.last_rerank_ms is not None and r.last_rerank_ms >= 0
    res = await r.search("q", eval_principal(), 8)
    assert [c.chunk_id for c in res.chunks] == [3, 2, 1, 4, 5, 6, 7, 8]  # 7 ở đuôi, không vượt lên
    await r.aclose()
    assert inner.closed


async def test_decorator_degrades_on_rerank_failure():
    r = backends.RerankingRetriever(Inner(5), FakeReranker(fail=True), top_n=3)
    res = await r.search("q", eval_principal(), 5)
    assert [c.chunk_id for c in res.chunks] == [1, 2, 3, 4, 5]
    assert res.mode == "hybrid+rerank_skipped"


async def test_runner_records_rerank_latency_per_question_and_aggregates():
    r = backends.RerankingRetriever(Inner(4), FakeReranker({2: 1.0}), top_n=4)
    qs = [Question("q1", "a", (("d", "2"),)), Question("q2", "b", (("d", "1"),))]
    res = await runner.run_config("vector_rerank", r, qs, eval_principal(), k=4)
    assert all(x.rerank_ms is not None for x in res.results)
    lat = res.latency()
    assert {"p50", "p95", "rerank_p50", "rerank_p95"} <= set(lat)
    report = runner.build_report(
        {"vector_rerank": res}, run_id="r", started_at="t", suite="s", dataset={}, versions={}, fake=True
    )  # fmt: skip
    pq = report["configs"]["vector_rerank"]["per_question"]  # type: ignore[index]
    assert all("rerank_ms" in x for x in pq)


async def test_runner_without_rerank_has_no_rerank_latency_keys():
    class Plain(Inner):
        pass

    res = await runner.run_config(
        "hybrid", Plain(3), [Question("q1", "a", (("d", "1"),))], eval_principal(), k=3
    )
    assert set(res.latency()) == {"p50", "p95"} and res.results[0].rerank_ms is None


def test_fake_factory_supports_rerank_configs(raw: Path):
    build = backends.fake_factory(raw)
    r = build("hybrid_rerank@top10")
    assert isinstance(r, backends.RerankingRetriever) and r._top_n == 10
