"""`CitationVerifier`: kiểm từng cặp (câu, đoạn được trích) bằng `SupportJudge` (rag-citations §5.3).

Chỉ phụ thuộc port. Không bao giờ coi lỗi judge là `supported`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Literal

from ..ports.support_judge import SupportJudge, SupportVerdict, Verdict
from .citations import Passage
from .sentences import Sentence

log = logging.getLogger("agent.verify")


@dataclass(frozen=True)
class VerifyConfig:
    max_concurrency: int = 4
    max_pairs: int = 12
    require_citation: bool = True
    on_unsupported: Literal["flag", "drop"] = "flag"
    min_supported_ratio: float = 0.5


@dataclass
class PairResult:
    sentence_id: int
    n: int
    verdict: Verdict
    evidence: tuple[int, int] | None = None  # vị trí trong văn bản đoạn (chưa cộng char_start)


@dataclass
class VerifyStats:
    pairs: int = 0
    judge_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    judge_errors: int = 0
    evidence_mismatch: int = 0


@dataclass
class VerifyOutcome:
    sentence_verdicts: dict[int, Verdict | None]  # None = không phải khẳng định
    pairs: list[PairResult]
    stats: VerifyStats


def locate_quote(passage: str, quote: str) -> tuple[int, int] | None:
    """Vị trí `quote` trong `passage`, bỏ qua khác biệt khoảng trắng; None nếu không là chuỗi con."""
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), passage)
    return (m.start(), m.end()) if m else None


def merge_verdicts(vs: list[Verdict]) -> Verdict:
    """supported > partial > unverified > unsupported (rag-citations §5.3 bước 4)."""
    for v in ("supported", "partial", "unverified"):
        if v in vs:
            return v  # type: ignore[return-value]
    return "unsupported"


class CitationVerifier:
    def __init__(self, judge: SupportJudge, cfg: VerifyConfig) -> None:
        self._judge = judge
        self._cfg = cfg

    async def verify(
        self, sentences: list[Sentence], passages_by_n: dict[int, Passage]
    ) -> VerifyOutcome:
        stats = VerifyStats()
        verdicts: dict[int, Verdict | None] = {}
        todo: list[tuple[Sentence, int]] = []
        for s in sentences:
            if not s.claim:
                verdicts[s.id] = None
            elif not [n for n in s.cites if n in passages_by_n]:
                verdicts[s.id] = "unsupported" if self._cfg.require_citation else None
            else:
                todo.extend((s, n) for n in s.cites if n in passages_by_n)
        sem = asyncio.Semaphore(max(1, self._cfg.max_concurrency))

        async def one(s: Sentence, n: int) -> PairResult:
            p = passages_by_n[n]
            async with sem:
                try:
                    v = await self._judge.judge(s.text, p.text)
                except Exception as exc:  # judge hỏng không được làm hỏng câu trả lời
                    log.warning("judge_failed", extra={"fields": {"type": type(exc).__name__}})
                    stats.judge_errors += 1
                    return PairResult(s.id, n, "unverified")
            return self._apply(s.id, n, p, v, stats)

        judged, skipped = todo[: self._cfg.max_pairs], todo[self._cfg.max_pairs :]
        stats.pairs = len(todo)
        results = list(await asyncio.gather(*(one(s, n) for s, n in judged)))
        results += [PairResult(s.id, n, "unverified") for s, n in skipped]
        for s in sentences:
            vs = [r.verdict for r in results if r.sentence_id == s.id]
            if vs:
                verdicts[s.id] = merge_verdicts(vs)
        return VerifyOutcome(verdicts, results, stats)

    @staticmethod
    def _apply(sid: int, n: int, p: Passage, v: SupportVerdict, stats: VerifyStats) -> PairResult:
        stats.judge_calls += v.calls
        stats.input_tokens += v.input_tokens
        stats.output_tokens += v.output_tokens
        if v.verdict == "unverified":
            stats.judge_errors += 1
            return PairResult(sid, n, "unverified")
        span = locate_quote(p.text, v.evidence_quote)
        verdict: Verdict = v.verdict
        if verdict == "supported" and span is None:
            verdict = "partial"  # khẳng định "đủ" mà không chỉ ra được bằng chứng thật trong đoạn
            stats.evidence_mismatch += 1
        return PairResult(sid, n, verdict, span if verdict in ("supported", "partial") else None)


__all__ = [
    "CitationVerifier",
    "VerifyConfig",
    "VerifyOutcome",
    "VerifyStats",
    "PairResult",
    "locate_quote",
    "merge_verdicts",
]
