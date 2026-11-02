"""Metric kiểm chứng trích dẫn của agent (cache-observability.md §3).

Registry riêng của module (counter dùng chung cho mọi app); `/metrics` nối với registry HTTP.
Nhãn chỉ gồm tập hữu hạn: trạng thái câu trả lời và phán quyết của câu. Không nhãn theo user,
thread hay nội dung. Tỉ lệ kiểm chứng đạt = `agent_claims_total{verdict="supported"}` chia tổng.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter

from .services.answer import FinalAnswer

REGISTRY = CollectorRegistry()

answers_total = Counter(
    "agent_answers_total",
    "Câu trả lời có trích dẫn theo trạng thái",
    ["status"],
    registry=REGISTRY,
)
claims_total = Counter(
    "agent_claims_total",
    "Câu khẳng định đã kiểm chứng theo phán quyết",
    ["verdict"],
    registry=REGISTRY,
)

_VERDICTS = ("supported", "partial", "unsupported", "unverified")


def verification_counts(ans: FinalAnswer) -> tuple[int, int, int]:
    """`(claims, verified, failed)`: câu có phán quyết; `supported`; `unsupported`."""
    vs = [s.get("verdict") for s in ans.sentences if s.get("verdict")]
    return len(vs), vs.count("supported"), vs.count("unsupported")


def record_verification(ans: FinalAnswer) -> None:
    answers_total.labels(ans.answer_status).inc()
    if not ans.verify.get("enabled"):
        return
    for s in ans.sentences:
        v = s.get("verdict")
        if v:
            claims_total.labels(v if v in _VERDICTS else "unverified").inc()
