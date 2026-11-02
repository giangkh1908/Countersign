"""Dựng câu trả lời cuối có trích dẫn: resolve mã -> (kiểm chứng) -> xử lý câu không được hỗ trợ -> từ chối.

Hàm thuần theo nghĩa không có I/O ngoài `SupportJudge` được truyền vào (rag-citations §5.1, §5.3, §5.4).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from .citation_verifier import CitationVerifier, VerifyConfig, VerifyOutcome, merge_verdicts
from .citations import Citation, CitationResolver, Passage
from .sentences import Sentence, split_sentences

REFUSAL_TEXT = "Không tìm thấy trong tài liệu. Bạn thử diễn đạt lại câu hỏi hoặc nêu rõ văn bản, số Điều cần tra."
_NOT_FOUND = re.compile(r"(?i)^\s*(?:xin lỗi,?\s*)?không tìm thấy")
_CITE = re.compile(r"\[(\d+)\]")
FRAME_BUDGET_BYTES = 60_000  # dưới trần 64 KiB của BFF (rag-citations §5.4)

_DEFINITE = ("supported", "partial", "unsupported")
AnswerStatus = Literal["answered", "partially_verified", "refused"]


@dataclass
class FinalAnswer:
    text: str
    items: list[dict[str, Any]] = field(default_factory=list)
    sentences: list[dict[str, Any]] = field(default_factory=list)
    answer_status: AnswerStatus = "answered"
    verify: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """Dữ liệu sự kiện SSE `citations` (rag-citations §5.4)."""
        return {
            "items": self.items,
            "sentences": self.sentences,
            "answer_status": self.answer_status,
            "verify": self.verify,
        }


def refusal(
    *, enabled: bool, invalid_refs: int = 0, verify: dict[str, Any] | None = None
) -> FinalAnswer:
    v = verify or {"enabled": enabled, "pairs": 0, "judge_calls": 0, "ms": 0}
    return FinalAnswer(REFUSAL_TEXT, [], [], "refused", {**v, "invalid_refs": invalid_refs})


def _rebuild(
    text: str, sentences: list[Sentence], keep: set[int]
) -> tuple[str, list[Sentence], dict[int, int], dict[int, int]]:
    """Giữ các câu trong `keep`, đánh số lại `[n]` và id câu. Trả `(text, câu mới, map id cũ->mới, map n cũ->mới)`."""
    kept = [s for s in sentences if s.id in keep]
    n_map: dict[int, int] = {}
    for s in kept:
        for n in _CITE.findall(text[s.start : s.end]):
            n_map.setdefault(int(n), len(n_map) + 1)
    parts: list[str] = []
    new: list[Sentence] = []
    id_map: dict[int, int] = {}
    pos = 0
    for i, s in enumerate(kept):
        piece = _CITE.sub(lambda m: f"[{n_map[int(m.group(1))]}]", text[s.start : s.end])
        gap = ""
        if i + 1 < len(kept):
            nxt = sentences[s.id + 1].start if s.id + 1 < len(sentences) else s.end
            gap = text[s.end : nxt] or " "
        id_map[s.id] = len(new)
        body = _CITE.sub(lambda m: f"[{n_map[int(m.group(1))]}]", s.text)
        new.append(
            Sentence(
                len(new),
                pos,
                pos + len(piece),
                body,
                [n_map[c] for c in s.cites if c in n_map],
                s.claim,
            )
        )
        parts += [piece, gap]
        pos += len(piece) + len(gap)
    return "".join(parts), new, id_map, n_map


def _evidence(
    outcome: VerifyOutcome, n: int, p: Passage, ids: set[int]
) -> tuple[int | None, int | None]:
    for want in ("supported", "partial"):
        for r in outcome.pairs:
            if r.n == n and r.sentence_id in ids and r.verdict == want and r.evidence:
                if p.char_start is None:
                    return None, None
                return p.char_start + r.evidence[0], p.char_start + r.evidence[1]
    return None, None


def fit_frame(payload: dict[str, Any], budget: int = FRAME_BUDGET_BYTES) -> dict[str, Any]:
    """Cắt `passage` (đặt `passage_truncated`) cho đến khi khung JSON vừa trong `budget` byte UTF-8."""
    import json

    cap = 4000
    while len(json.dumps(payload, ensure_ascii=False).encode()) > budget and cap > 200:
        cap = max(200, int(cap * 0.6))
        for it in payload["items"]:
            if len(it.get("passage", "")) > cap:
                it["passage"] = it["passage"][:cap]
                it["passage_truncated"] = True
    return payload


async def build_answer(
    draft: str,
    retrieved: dict[str, Passage],
    verifier: CitationVerifier | None,
    cfg: VerifyConfig,
) -> FinalAnswer:
    t0 = time.monotonic()
    rr = CitationResolver().resolve(draft, retrieved)
    by_n = {i + 1: retrieved[str(cid)] for i, cid in enumerate(rr.order)}
    text = rr.text.strip()
    if verifier is None:
        items = [Citation.from_passage(n, p).model_dump() for n, p in by_n.items()]
        status: AnswerStatus = "refused" if not items and _NOT_FOUND.match(text) else "answered"
        verify = {
            "enabled": False,
            "pairs": 0,
            "judge_calls": 0,
            "ms": 0,
            "invalid_refs": rr.invalid_refs,
        }
        return FinalAnswer(text, items, [], status, verify)

    sentences = split_sentences(text)
    outcome = await verifier.verify(sentences, by_n)
    verdicts0 = outcome.sentence_verdicts
    stats = outcome.stats
    # Từ chối khi không đủ nguồn (bước 6b): chỉ tính câu có phán quyết dứt khoát (bỏ unverified/không phải khẳng định).
    definite = [v for s in sentences if (v := verdicts0.get(s.id)) in _DEFINITE]
    n_ok = sum(1 for v in definite if v in ("supported", "partial"))
    n_sup = sum(1 for v in definite if v == "supported")
    refuse = bool(definite) and (n_ok == 0 or n_sup / len(definite) < cfg.min_supported_ratio)
    dropped = (
        {s.id for s in sentences if verdicts0.get(s.id) == "unsupported"}
        if cfg.on_unsupported == "drop" and not refuse
        else set()
    )
    verify = {
        "enabled": True,
        "pairs": stats.pairs,
        "judge_calls": stats.judge_calls,
        "ms": int((time.monotonic() - t0) * 1000),
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "judge_errors": stats.judge_errors,
        "evidence_mismatch": stats.evidence_mismatch,
        "invalid_refs": rr.invalid_refs,
        "dropped_sentences": len(dropped),
    }
    if refuse:
        return refusal(enabled=True, invalid_refs=rr.invalid_refs, verify=verify)
    if dropped:
        keep = {s.id for s in sentences} - dropped
        text, sentences, id_map, n_map = _rebuild(text, sentences, keep)
        outcome = _remap(outcome, id_map, n_map)
        by_n = {n_map[n]: p for n, p in by_n.items() if n in n_map}
    verdicts = outcome.sentence_verdicts

    items: list[dict[str, Any]] = []
    for n, p in sorted(by_n.items()):
        ids = {s.id for s in sentences if n in s.cites}
        vs = [r.verdict for r in outcome.pairs if r.n == n and r.sentence_id in ids]
        c = Citation.from_passage(n, p)
        c.verdict = merge_verdicts(vs) if vs else "unverified"
        c.sentence_ids = sorted(ids)
        c.evidence_start, c.evidence_end = _evidence(outcome, n, p, ids)
        items.append(c.model_dump())
    sents = [
        {
            "id": s.id,
            "start": s.start,
            "end": s.end,
            "cites": s.cites,
            "verdict": verdicts.get(s.id),
        }
        for s in sentences
    ]
    claim_v = [v for s in sentences if (v := verdicts.get(s.id)) is not None]
    if not claim_v and not items and _NOT_FOUND.match(text):
        status = "refused"
    elif any(v != "supported" for v in claim_v):
        status = "partially_verified"
    else:
        status = "answered"
    return FinalAnswer(text, items, sents, status, verify)


def _remap(outcome: VerifyOutcome, id_map: dict[int, int], n_map: dict[int, int]) -> VerifyOutcome:
    from .citation_verifier import PairResult

    pairs = [
        PairResult(id_map[r.sentence_id], n_map[r.n], r.verdict, r.evidence)
        for r in outcome.pairs
        if r.sentence_id in id_map and r.n in n_map
    ]
    verdicts = {id_map[i]: v for i, v in outcome.sentence_verdicts.items() if i in id_map}
    return VerifyOutcome(verdicts, pairs, outcome.stats)
