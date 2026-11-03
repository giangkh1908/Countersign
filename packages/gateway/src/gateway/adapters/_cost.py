"""Đọc chi phí do provider tự báo trong `usage.cost` (USD) của wire OpenAI-compatible. Trường tuỳ chọn."""

from __future__ import annotations

from typing import Any


def reported_cost(usage: dict[str, Any] | None) -> float | None:
    """`usage.cost` nếu là số không âm; thiếu hoặc giá trị lạ -> None (dùng bảng giá thay thế)."""
    c = (usage or {}).get("cost")
    if isinstance(c, bool) or not isinstance(c, int | float) or c < 0:
        return None
    return float(c)
