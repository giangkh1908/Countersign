"""Biến thể cấu hình, bootstrap và chẩn đoán RRF (hàm thuần, không cần Postgres)."""

from __future__ import annotations

import pytest
from mcp_docs.ports import RetrievedChunk

from eval.rag import backends, diagnose, metrics


def test_config_overrides_ghep_hau_to():
    o = backends.config_overrides("hybrid@stop+wfts0.25")
    assert o["docs_fts_stopwords"] is True and o["docs_rrf_weight_fts"] == 0.25
    assert o["docs_use_vector"] is True and o["docs_use_fts"] is True


def test_config_overrides_loi():
    with pytest.raises(backends.UnsupportedConfig):
        backends.config_overrides("hybrid@khong_co")
    with pytest.raises(backends.UnsupportedConfig):
        backends.config_overrides("khong_co")


def test_parse_configs():
    assert backends.parse_configs("default") == backends.GROUPS["default"]
    assert backends.parse_configs("vector, hybrid@rank") == ("vector", "hybrid@rank")
    # mọi cấu hình trong nhóm sweep hợp lệ
    for name in backends.GROUPS["sweep"]:
        backends.config_overrides(name)


def test_bootstrap_ci_tat_dinh_va_bao_gom_trung_binh():
    vals = [1.0] * 30 + [0.0] * 10
    lo, hi = metrics.bootstrap_ci(vals)
    assert (lo, hi) == metrics.bootstrap_ci(vals)
    assert lo < 0.75 < hi and lo >= 0.0 and hi <= 1.0
    assert metrics.bootstrap_ci([1.0] * 10) == (1.0, 1.0)
    assert metrics.bootstrap_ci([]) == (0.0, 0.0)


def test_paired_bootstrap_delta():
    a, b = [1.0, 1.0, 1.0, 0.0], [0.0, 1.0, 0.0, 0.0]
    d, lo, hi = metrics.paired_bootstrap_delta(a, b)
    assert d == pytest.approx(0.5) and lo <= d <= hi
    with pytest.raises(ValueError):
        metrics.paired_bootstrap_delta([1.0], [1.0, 0.0])


def _c(cid: int, art: str, vec: int | None, fts: int | None, w: float = 1.0) -> RetrievedChunk:
    score = (1 / (60 + vec) if vec else 0) + (w / (60 + fts) if fts else 0)
    return RetrievedChunk(
        chunk_id=cid, doc_id="d", title="t", heading=None, source=f"s#{cid}", ord=cid,
        department="ALL", classification=0, allowed_roles=(), content="x", score=score,
        vec_rank=vec, fts_rank=fts, doc_num="D", article=art,
    )  # fmt: skip


def test_classify_overlap_bonus():
    # đúng: vector hạng 1, vắng FTS; chen: hạng 40 ở cả hai nhánh => RRF cao hơn nhờ cộng hai nhánh
    gold = _c(1, "1", 1, None)
    intr = _c(2, "2", 40, 40)
    union = sorted([gold, intr], key=lambda c: -c.score)
    assert union[0] is intr  # 2/(100) = 0.02 > 1/61 = 0.0164
    r = diagnose.classify(union, {("D", "1")})
    assert r["cause"] == "overlap_bonus"
    assert r["intruder_rrf_ge_top1_single_branch"] == [True]
    assert r["hit_under_weight"]["0.1"] is True  # type: ignore[index]


def test_classify_fts_xep_thap_va_khac():
    gold = _c(1, "1", 1, 30)
    intr = _c(2, "2", 5, 2)
    union = sorted([gold, intr], key=lambda c: -c.score)
    assert union[0] is intr
    assert diagnose.classify(union, {("D", "1")})["cause"] == "fts_xep_thap"
    # chen chỉ ở một nhánh => không thuộc hai loại trên
    only_fts = _c(3, "3", None, 1)
    union = sorted([_c(1, "1", 2, None), only_fts], key=lambda c: -c.score)
    assert diagnose.classify(union, {("D", "1")})["cause"] == "khac"


def test_lexical_overlap_nho():
    from eval.rag.dataset import Question

    texts = {
        ("D", "1"): "Nghỉ hằng năm Người lao động nghỉ phép năm 12 ngày",
        ("D", "2"): "Chữ ký số có giá trị như chữ ký tay",
        ("D", "3"): "Trợ cấp thôi việc mỗi năm nửa tháng lương",
    }
    qs = [Question("q1", "Người lao động nghỉ phép năm bao nhiêu ngày?", (("D", "1"),))]
    r = diagnose.lexical_overlap(qs, texts)
    assert r["n"] == 1
    assert r["token_cov_gold"]["mean"] == 1.0  # type: ignore[index]
    assert r["idf_overlap_ranker_hit@5"]["value"] == 1.0  # type: ignore[index]
