"""Tính chi phí một lượt gọi model. Ưu tiên: provider tự báo > bảng giá theo alias > 0.

Không biết tên vendor: chỉ dùng trường trung lập `cost_usd` của port và `Price` của catalog.
"""

from __future__ import annotations

from .catalog import Price


def cost_usd(
    reported: float | None, price: Price | None, input_tokens: int, output_tokens: int = 0
) -> float:
    """Chi phí USD (không âm)."""
    if reported is not None:
        return max(0.0, reported)
    if price is None:
        return 0.0
    usd = (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1_000_000
    return max(0.0, usd)


def to_micro_usd(usd: float) -> int:
    """USD -> micro-USD nguyên, làm tròn, không âm."""
    return max(0, round(usd * 1_000_000))
