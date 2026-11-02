"""Chẩn đoán vì sao hybrid (RRF) kém vector, và đo mức trùng từ giữa câu hỏi và Điều đúng.

Chạy: `uv run --all-packages python -m eval.rag diagnose --suite vbpl-v1` (cần Postgres đã ingest
và gateway embedding, như `run`). Chỉ đọc, không đổi cấu hình hay dữ liệu.

Phần 1 (RRF): với mỗi câu mà vector có Điều đúng trong top-5 nhưng hybrid thì không, ghi hạng của
chunk đúng trong từng nhánh (`vec_rank`, `fts_rank`), điểm RRF, và các chunk đứng trên nó. Rồi xếp vào:
  - `overlap_bonus`  : chunk đúng KHÔNG có trong nhánh FTS, và có chunk khác đứng trên nó nhờ có mặt
                       ở cả hai nhánh dù vector xếp chunk đó thấp hơn chunk đúng (cơ chế giả thuyết);
  - `fts_xep_thap`   : chunk đúng có trong FTS nhưng FTS xếp nó thấp hơn chunk chen vào, và vector
                       xếp chen thấp hơn chunk đúng (cùng kiểu chen, nhưng do FTS xếp sai chứ không do vắng mặt);
  - `khac`           : còn lại.
Kèm phản thực tế tính ngay từ danh sách hạng đã có: nếu trọng số FTS là w thì Điều đúng có vào top-5 không.

Phần 2 (trùng từ): vì bộ câu hỏi được viết sau khi đọc chính Điều đó, đo độ phủ từ nội dung của câu hỏi
trong Điều đúng, so với các Điều ngẫu nhiên, và recall@5 của một bộ xếp hạng trùng từ có trọng số IDF
thuần Python (không Postgres, không embedding) làm mốc "giải được bằng từ vựng đến đâu".
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path

from acme_common.ports import Principal
from mcp_docs.ports import DocumentRetriever, RetrievedChunk
from mcp_docs.services.fts_query import VI_STOPWORDS

from . import metrics
from .dataset import Question, article_file

RRF_K = 60
WEIGHTS = (1.0, 0.5, 0.25, 0.1)
TOP = 5
_TOKEN = re.compile(r"\w+", re.UNICODE)


# ---------------------------------------------------------------- phần 1: RRF


def _article_ranking(chunks: list[RetrievedChunk]) -> list[tuple[str, str]]:
    return metrics.dedupe_ranking([(c.doc_num or "", c.article or "") for c in chunks])


def _gold_chunk(chunks: list[RetrievedChunk], gold: set[tuple[str, str]]) -> RetrievedChunk | None:
    for c in chunks:  # chunks đã sắp theo RRF giảm dần
        if (c.doc_num or "", c.article or "") in gold:
            return c
    return None


def _rrf(c: RetrievedChunk, w_fts: float) -> float:
    s = 1.0 / (RRF_K + c.vec_rank) if c.vec_rank is not None else 0.0
    if c.fts_rank is not None:
        s += w_fts / (RRF_K + c.fts_rank)
    return s


def _hit_under_weight(
    union: list[RetrievedChunk], gold: set[tuple[str, str]], w_fts: float
) -> bool:
    ordered = sorted(union, key=lambda c: (-_rrf(c, w_fts), c.chunk_id))
    return any(a in gold for a in _article_ranking(ordered)[:TOP])


def classify(union: list[RetrievedChunk], gold: set[tuple[str, str]]) -> dict[str, object]:
    """Phân loại một câu hybrid sai; `union` là mọi chunk của hai nhánh, đã sắp theo RRF."""
    g = _gold_chunk(union, gold)
    if g is None:
        return {"cause": "khac", "why": "chunk đúng không có ở nhánh nào", "gold": None}
    ahead: list[RetrievedChunk] = []
    seen: set[tuple[str, str]] = set()
    for c in union:
        key = (c.doc_num or "", c.article or "")
        if key in gold:
            break
        if key not in seen:
            seen.add(key)
            ahead.append(c)
    intruders = ahead[:TOP]
    both_worse_vec = [
        c
        for c in intruders
        if c.vec_rank is not None
        and c.fts_rank is not None
        and (g.vec_rank is None or c.vec_rank > g.vec_rank)
    ]
    if g.fts_rank is None and both_worse_vec:
        cause = "overlap_bonus"
    elif g.fts_rank is not None and any(
        c.fts_rank < g.fts_rank for c in both_worse_vec if c.fts_rank is not None
    ):
        cause = "fts_xep_thap"
    else:
        cause = "khac"
    return {
        "cause": cause,
        "gold": _row(g, union),
        "intruders": [_row(c, union) for c in intruders],
        "intruder_rrf_ge_top1_single_branch": [c.score >= 1.0 / (RRF_K + 1) for c in intruders],
        "hit_under_weight": {str(w): _hit_under_weight(union, gold, w) for w in WEIGHTS},
    }


def _row(c: RetrievedChunk, union: list[RetrievedChunk]) -> dict[str, object]:
    return {
        "article": f"{c.doc_num}/Điều {c.article}",
        "chunk_id": c.chunk_id,
        "vec_rank": c.vec_rank,
        "fts_rank": c.fts_rank,
        "rrf": round(c.score, 5),
        "pos": next(i for i, u in enumerate(union, 1) if u.chunk_id == c.chunk_id),
    }


async def diagnose_rrf(
    vector: DocumentRetriever,
    hybrid: DocumentRetriever,
    questions: list[Question],
    principal: Principal,
) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    n = vec_ok = hyb_ok = 0
    fts_absent = 0
    for q in questions:
        if not q.answerable or not q.gold:
            continue
        gold = set(q.gold)
        n += 1
        vres = await vector.search(q.question, principal, 50)
        hres = await hybrid.search(q.question, principal, 500)
        v_hit = bool(gold & set(_article_ranking(vres.chunks)[:TOP]))
        h_hit = bool(gold & set(_article_ranking(hres.chunks)[:TOP]))
        vec_ok += v_hit
        hyb_ok += h_hit
        g = _gold_chunk(hres.chunks, gold)
        fts_absent += g is None or g.fts_rank is None
        if v_hit and not h_hit:
            cases.append({"id": q.id, "question": q.question, **classify(hres.chunks, gold)})
        elif h_hit and not v_hit:
            cases.append({"id": q.id, "question": q.question, "cause": "hybrid_dung_vector_sai"})
    wrong = [c for c in cases if c["cause"] != "hybrid_dung_vector_sai"]
    counts = Counter(str(c["cause"]) for c in wrong)
    fix = {
        str(w): sum(1 for c in wrong if c.get("hit_under_weight", {}).get(str(w))) for w in WEIGHTS
    }
    return {
        "n": n,
        "vector_hit@5": vec_ok,
        "hybrid_hit@5": hyb_ok,
        "hybrid_sai_vector_dung": len(wrong),
        "theo_nguyen_nhan": dict(counts),
        "gold_vang_o_nhanh_fts": fts_absent,
        "so_cau_dung_lai_voi_trong_so_fts": fix,
        "cases": cases,
    }


# ---------------------------------------------------------------- phần 2: trùng từ


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize("NFC", text).lower())


def load_article_texts(raw: Path, doc_nums: list[str]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for d in doc_nums:
        for a in json.loads(article_file(raw, d).read_text(encoding="utf-8")):
            body = " ".join(str(p) for p in a.get("paragraphs", []))
            out[(d, str(a["article"]))] = f"{a.get('heading', '')} {body}"
    return out


def lexical_overlap(
    questions: list[Question], texts: dict[tuple[str, str], str], *, seed: int = 42
) -> dict[str, object]:
    """Độ phủ từ nội dung của câu hỏi trong Điều đúng, mốc ngẫu nhiên và mốc xếp hạng trùng từ."""
    keys = list(texts)
    tok = {k: set(_tokens(t)) for k, t in texts.items()}
    big = {k: set(zip(_tokens(t), _tokens(t)[1:], strict=False)) for k, t in texts.items()}
    df: Counter[str] = Counter(w for s in tok.values() for w in s)
    n_art = len(keys)
    idf = {w: math.log((n_art + 1) / (c + 0.5)) for w, c in df.items()}
    rng = random.Random(seed)

    def content(qtoks: list[str]) -> list[str]:
        return [t for t in dict.fromkeys(qtoks) if t not in VI_STOPWORDS]

    rows: list[dict[str, object]] = []
    hit5: list[float] = []
    for q in questions:
        if not q.answerable or not q.gold:
            continue
        qt = _tokens(q.question)
        ct = content(qt)
        if not ct:
            continue
        qb = {
            (a, b)
            for a, b in zip(qt, qt[1:], strict=False)
            if a not in VI_STOPWORDS and b not in VI_STOPWORDS
        }
        g = q.gold[0]
        cov = sum(t in tok[g] for t in ct) / len(ct)
        bcov = (sum(b in big[g] for b in qb) / len(qb)) if qb else None
        rnd = rng.sample(keys, min(200, len(keys)))
        cov_rnd = statistics.fmean(sum(t in tok[k] for t in ct) / len(ct) for k in rnd)

        def score(k: tuple[str, str], ct: list[str] = ct) -> float:
            return sum(idf.get(t, 0.0) for t in ct if t in tok[k]) / (
                sum(idf.get(t, 0.0) for t in ct) or 1.0
            )

        ranked = sorted(keys, key=lambda k: (-score(k), k))
        top = {k for k in ranked[:TOP]}
        hit5.append(1.0 if set(q.gold) & top else 0.0)
        rows.append(
            {
                "id": q.id,
                "n_content_tokens": len(ct),
                "token_cov_gold": round(cov, 3),
                "token_cov_random_mean": round(cov_rnd, 3),
                "bigram_cov_gold": None if bcov is None else round(bcov, 3),
            }
        )
    cov = [float(r["token_cov_gold"]) for r in rows]  # type: ignore[arg-type]
    cov_r = [float(r["token_cov_random_mean"]) for r in rows]  # type: ignore[arg-type]
    bcv = [float(r["bigram_cov_gold"]) for r in rows if r["bigram_cov_gold"] is not None]  # type: ignore[arg-type]
    lo, hi = metrics.bootstrap_ci(hit5, seed=seed)
    return {
        "n": len(rows),
        "token_cov_gold": {"mean": statistics.fmean(cov), "median": statistics.median(cov)},
        "token_cov_random": {"mean": statistics.fmean(cov_r)},
        "token_cov_gold_ge_0.5": sum(c >= 0.5 for c in cov),
        "bigram_cov_gold": {
            "mean": statistics.fmean(bcv) if bcv else None,
            "n_with_bigrams": len(bcv),
            "n_zero": sum(b == 0 for b in bcv),
        },
        "idf_overlap_ranker_hit@5": {"value": statistics.fmean(hit5), "ci95": [lo, hi]},
        "rows": rows,
    }
