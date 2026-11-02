"""Chỉ số truy xuất trên ví dụ tính tay."""

from __future__ import annotations

import math

import pytest

from eval.rag import metrics

A, B, C, D, E = (("d", x) for x in "ABCDE")


def test_dedupe_giu_vi_tri_dau_tien():
    assert metrics.dedupe_ranking([A, A, B, A, C, B]) == [A, B, C]


def test_recall_hai_gold_mot_trung():
    # ranked A B C, gold {C, E}: top-2 không có gold nào, top-3 có C => 1/2.
    assert metrics.recall_at_k([A, B, C], [C, E], 2) == 0.0
    assert metrics.recall_at_k([A, B, C], [C, E], 3) == 0.5


def test_recall_gop_chunk_cung_dieu_truoc_khi_cat():
    # Điều A có 3 chunk liền nhau; sau khi gộp B vẫn nằm trong top-2.
    assert metrics.recall_at_k([A, A, A, B], [B], 2) == 1.0


def test_hit_at_k():
    assert metrics.hit_at_k([A, B, C], [C, E], 2) == 0.0
    assert metrics.hit_at_k([A, B, C], [C, E], 3) == 1.0


def test_mrr_vi_tri_thu_ba():
    assert metrics.reciprocal_rank([A, B, C], [C]) == pytest.approx(1 / 3)


def test_mrr_lay_gold_dau_tien_trong_nhieu_gold():
    assert metrics.reciprocal_rank([A, B, C, D], [D, B]) == pytest.approx(1 / 2)


def test_mrr_gop_trung_truoc_khi_dem_vi_tri():
    assert metrics.reciprocal_rank([A, A, B], [B]) == pytest.approx(1 / 2)


def test_mrr_ngoai_max_rank_la_khong():
    ranked = [("d", str(i)) for i in range(11)]
    assert metrics.reciprocal_rank(ranked, [("d", "10")], max_rank=10) == 0.0
    assert metrics.reciprocal_rank(ranked, [("d", "10")], max_rank=None) == pytest.approx(1 / 11)


def test_ndcg_mot_gold_o_hang_hai():
    # DCG = 1/log2(3); IDCG = 1.
    assert metrics.ndcg_at_k([B, A], [A], 3) == pytest.approx(1 / math.log2(3))


def test_ndcg_hai_gold_hoan_hao_va_dao_thu_tu():
    assert metrics.ndcg_at_k([A, B], [A, B], 2) == pytest.approx(1.0)
    assert metrics.ndcg_at_k([B, A], [A, B], 2) == pytest.approx(1.0)  # độ lợi nhị phân


def test_ndcg_hai_gold_mot_cai_o_hang_ba():
    # ranked A X B, gold {A, B}: DCG = 1 + 1/log2(4) = 1.5; IDCG = 1 + 1/log2(3).
    x = ("d", "X")
    expected = 1.5 / (1 + 1 / math.log2(3))
    assert metrics.ndcg_at_k([A, x, B], [A, B], 3) == pytest.approx(expected)


def test_ndcg_idcg_bi_cat_boi_k():
    # 3 gold nhưng k=2: IDCG = 1 + 1/log2(3).
    idcg = 1 + 1 / math.log2(3)
    assert metrics.ndcg_at_k([A, B, C], [A, B, C], 2) == pytest.approx(1.0)
    assert metrics.ndcg_at_k([A, D], [A, B, C], 2) == pytest.approx(1 / idcg)


def test_khong_co_ket_qua_dung_thi_moi_chi_so_bang_khong():
    ranked, gold = [A, B, C], [D]
    assert metrics.recall_at_k(ranked, gold, 10) == 0.0
    assert metrics.hit_at_k(ranked, gold, 10) == 0.0
    assert metrics.reciprocal_rank(ranked, gold) == 0.0
    assert metrics.ndcg_at_k(ranked, gold, 10) == 0.0


def test_danh_sach_xep_hang_rong():
    assert metrics.recall_at_k([], [A], 5) == 0.0
    assert metrics.reciprocal_rank([], [A]) == 0.0
    assert metrics.ndcg_at_k([], [A], 5) == 0.0


def test_gold_rong_la_loi():
    for fn in (
        lambda: metrics.recall_at_k([A], [], 5),
        lambda: metrics.hit_at_k([A], [], 5),
        lambda: metrics.reciprocal_rank([A], []),
        lambda: metrics.ndcg_at_k([A], [], 5),
    ):
        with pytest.raises(ValueError):
            fn()


def test_k_khong_hop_le():
    with pytest.raises(ValueError):
        metrics.recall_at_k([A], [A], 0)


def test_mean():
    assert metrics.mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)
    assert metrics.mean([]) == 0.0
