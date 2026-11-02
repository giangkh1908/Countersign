"""Chỉ số truy xuất (rag-citations.md §7.3): hàm thuần, không I/O.

Đơn vị chấm là Điều: khoá `(doc_num, article)`. Danh sách xếp hạng được gộp các chunk cùng khoá,
giữ vị trí xuất hiện đầu tiên, rồi mới cắt top-k, để việc cắt một Điều dài thành nhiều chunk
không làm đổi điểm.

Các hàm theo từng câu hỏi yêu cầu `gold` không rỗng (câu không có đáp án không tham gia chấm
truy xuất); gold rỗng gây `ValueError` để lỗi dữ liệu không bị che thành điểm 0.
"""

from __future__ import annotations

import math
import random
from collections.abc import Hashable, Iterable, Sequence

Key = tuple[str, str]  # (doc_num, article)


def dedupe_ranking[T: Hashable](ranked: Iterable[T]) -> list[T]:
    """Gộp trùng, giữ vị trí xuất hiện đầu tiên."""
    seen: set[T] = set()
    out: list[T] = []
    for item in ranked:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _check(gold: Iterable[Hashable], k: int | None = None) -> frozenset[Hashable]:
    g = frozenset(gold)
    if not g:
        raise ValueError("gold rỗng: câu không có đáp án không được chấm truy xuất")
    if k is not None and k < 1:
        raise ValueError("k phải >= 1")
    return g


def recall_at_k[T: Hashable](ranked: Sequence[T], gold: Iterable[T], k: int) -> float:
    """|gold ∩ top-k| / |gold| trên danh sách đã gộp."""
    g = _check(gold, k)
    top = set(dedupe_ranking(ranked)[:k])
    return len(g & top) / len(g)


def hit_at_k[T: Hashable](ranked: Sequence[T], gold: Iterable[T], k: int) -> float:
    """1 nếu top-k chứa ít nhất một gold, ngược lại 0."""
    g = _check(gold, k)
    return 1.0 if g & set(dedupe_ranking(ranked)[:k]) else 0.0


def reciprocal_rank[T: Hashable](
    ranked: Sequence[T], gold: Iterable[T], max_rank: int | None = 10
) -> float:
    """1/vị trí (1-based) của mục đúng đầu tiên; 0 nếu không có (hoặc vượt `max_rank`)."""
    g = _check(gold)
    for i, item in enumerate(dedupe_ranking(ranked), start=1):
        if max_rank is not None and i > max_rank:
            break
        if item in g:
            return 1.0 / i
    return 0.0


def ndcg_at_k[T: Hashable](ranked: Sequence[T], gold: Iterable[T], k: int) -> float:
    """nDCG@k độ lợi nhị phân; mỗi gold chỉ ghi điểm một lần (đã đảm bảo nhờ gộp trùng)."""
    g = _check(gold, k)
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, item in enumerate(dedupe_ranking(ranked)[:k], start=1)
        if item in g
    )
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(g), k) + 1))
    return dcg / idcg


def mean(values: Sequence[float]) -> float:
    """Trung bình; danh sách rỗng cho 0.0 (nhóm không có câu nào)."""
    return sum(values) / len(values) if values else 0.0


def _resample_means(values: Sequence[float], n_boot: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    n = len(values)
    return sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))


def _percentiles(sorted_vals: Sequence[float], alpha: float) -> tuple[float, float]:
    n = len(sorted_vals)
    return sorted_vals[int(alpha / 2 * n)], sorted_vals[min(n - 1, int((1 - alpha / 2) * n))]


def bootstrap_ci(
    values: Sequence[float], *, n_boot: int = 1000, seed: int = 42, alpha: float = 0.05
) -> tuple[float, float]:
    """Khoảng tin cậy bootstrap (percentile) của trung bình, lấy mẫu lại theo câu hỏi.

    Với n nhỏ (vài chục câu) khoảng này rộng và hơi hẹp hơn thực tế ở sát 0 hoặc 1; chỉ là số đo
    độ bất định do chọn câu hỏi, không phải do chọn tham số.
    """
    if not values:
        return (0.0, 0.0)
    return _percentiles(_resample_means(values, n_boot, seed), alpha)


def paired_bootstrap_delta(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """(mean(a-b), lo, hi): bootstrap theo cặp trên cùng tập câu hỏi (a, b cùng thứ tự)."""
    if len(a) != len(b):
        raise ValueError("a và b phải cùng số câu")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    lo, hi = bootstrap_ci(diffs, n_boot=n_boot, seed=seed, alpha=alpha)
    return mean(diffs), lo, hi
