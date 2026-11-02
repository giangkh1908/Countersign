"""Chạy truy xuất cho 4 cấu hình, chấm điểm, dựng báo cáo.

Runner chỉ biết port `DocumentRetriever`. Cách dựng retriever cho từng cấu hình nằm ở
`RetrieverFactory` (thật: qua `mcp_docs.factory`; giả: `fakes.CorpusFakeRetriever`).
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from acme_common.ports import Principal
from mcp_docs.ports import DocumentRetriever

from . import metrics
from .dataset import Question

CONFIGS = ("vector", "fts", "fts_segmented", "hybrid", "hybrid_direct")
CONFIG_LABELS = {
    "vector": "chỉ vector",
    "fts": "chỉ FTS",
    "fts_segmented": "chỉ FTS (tách từ)",
    "hybrid": "hybrid (RRF)",
    "hybrid_direct": "hybrid + tra trực tiếp",
}
KS = (1, 3, 5, 10)
POOL = 50  # số chunk lấy về trước khi gộp theo Điều; đủ để còn >= 10 Điều

RetrieverFactory = Callable[[str], DocumentRetriever]


@dataclass(slots=True)
class QuestionResult:
    id: str
    type: str
    ranked: list[tuple[str, str]]  # đã gộp theo Điều, tối đa 10
    scores: dict[str, float]
    latency_ms: float


@dataclass(slots=True)
class ConfigResult:
    config: str
    results: list[QuestionResult] = field(default_factory=list)

    def aggregate(self, rows: Iterable[QuestionResult] | None = None) -> dict[str, float]:
        rows = list(self.results if rows is None else rows)
        out: dict[str, float] = {"n": float(len(rows))}
        for name in score_names():
            out[name] = metrics.mean([r.scores[name] for r in rows])
        return out

    def by_type(self) -> dict[str, dict[str, float]]:
        groups: dict[str, list[QuestionResult]] = defaultdict(list)
        for r in self.results:
            groups[r.type].append(r)
        return {t: self.aggregate(rows) for t, rows in sorted(groups.items())}

    def latency(self) -> dict[str, float]:
        xs = sorted(r.latency_ms for r in self.results)
        if not xs:
            return {"p50": 0.0, "p95": 0.0}
        return {"p50": xs[int(0.50 * (len(xs) - 1))], "p95": xs[int(0.95 * (len(xs) - 1))]}


def score_names() -> list[str]:
    return [f"recall@{k}" for k in KS] + [f"hit@{k}" for k in KS] + ["mrr", "ndcg@10"]


def score_question(
    ranked: list[tuple[str, str]], gold: Iterable[tuple[str, str]]
) -> dict[str, float]:
    g = list(gold)
    s = {f"recall@{k}": metrics.recall_at_k(ranked, g, k) for k in KS}
    s.update({f"hit@{k}": metrics.hit_at_k(ranked, g, k) for k in KS})
    s["mrr"] = metrics.reciprocal_rank(ranked, g, max_rank=10)
    s["ndcg@10"] = metrics.ndcg_at_k(ranked, g, 10)
    return s


async def run_config(
    config: str,
    retriever: DocumentRetriever,
    questions: Iterable[Question],
    principal: Principal,
    *,
    pool: int = POOL,
) -> ConfigResult:
    """Chỉ chấm câu `answerable` có gold (câu không đáp án do suite khác đo)."""
    res = ConfigResult(config)
    for q in questions:
        if not q.answerable or not q.gold:
            continue
        t0 = time.perf_counter()
        found = await retriever.search(q.question, principal, pool)
        ms = (time.perf_counter() - t0) * 1000
        keys = [(c.doc_num or "", c.article or "") for c in found.chunks]
        ranked = metrics.dedupe_ranking(keys)[:10]
        res.results.append(QuestionResult(q.id, q.type, ranked, score_question(ranked, q.gold), ms))
    return res


async def run_all(
    factory: RetrieverFactory,
    questions: list[Question],
    principal: Principal,
    configs: Iterable[str] = CONFIGS,
    on_done: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, ConfigResult]:
    out: dict[str, ConfigResult] = {}
    for name in configs:
        retriever = factory(name)
        try:
            out[name] = await run_config(name, retriever, questions, principal)
        finally:
            await retriever.aclose()
        if on_done:
            await on_done(name)
    return out


def format_table(results: dict[str, ConfigResult]) -> str:
    cols = ["recall@5", "recall@10", "hit@5", "mrr", "ndcg@10"]
    head = f"{'cấu hình':<26}{'n':>4}" + "".join(f"{c:>11}" for c in cols) + f"{'p50 ms':>9}"
    lines = [head, "-" * len(head)]
    for name, r in results.items():
        agg = r.aggregate()
        lines.append(
            f"{CONFIG_LABELS.get(name, name):<26}{int(agg['n']):>4}"
            + "".join(f"{agg[c]:>11.3f}" for c in cols)
            + f"{r.latency()['p50']:>9.1f}"
        )
    return "\n".join(lines)


def build_report(
    results: dict[str, ConfigResult],
    *,
    run_id: str,
    started_at: str,
    suite: str,
    dataset: dict[str, object],
    versions: dict[str, object],
    fake: bool,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "started_at": started_at,
        "suite": suite,
        "fake": fake,
        "dataset": dataset,
        "versions": versions,
        "ks": list(KS),
        "configs": {
            name: {
                "label": CONFIG_LABELS.get(name, name),
                "metrics": r.aggregate(),
                "by_type": r.by_type(),
                "latency_ms": r.latency(),
                "per_question": [
                    {"id": x.id, "ranked": [list(k) for k in x.ranked], "scores": x.scores}
                    for x in r.results
                ],
            }
            for name, r in results.items()
        },
    }
