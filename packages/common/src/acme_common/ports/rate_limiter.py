"""Port `RateLimiter`: `reserve`, `settle`, `acquire_slot(key_id, max)`, `release_slot(key_id)`.

Adapter v1 dự kiến: `redis_token_bucket`, `in_memory` (degraded, D5).
Milestone: M1.
Tài liệu: docs/design/00-contracts.md §9.2.
"""

from __future__ import annotations

import abc

from .types import LimitDecision


class RateLimiter(abc.ABC):
    @abc.abstractmethod
    async def reserve(
        self, key: str, cost: int, *, limit: int, window_s: float = 60.0
    ) -> LimitDecision:
        """Token bucket dung lượng `limit`, nạp lại đều trong `window_s`; trừ trước `cost`."""

    @abc.abstractmethod
    async def settle(self, key: str, reserved: int, actual: int) -> None:
        """Hoàn/trừ chênh lệch giữa đã giữ chỗ và thực tế."""

    @abc.abstractmethod
    async def acquire_slot(self, key_id: str, max_slots: int) -> LimitDecision:
        """Giới hạn đồng thời; `allowed=False` nếu đã đủ `max_slots`."""

    @abc.abstractmethod
    async def release_slot(self, key_id: str) -> None:
        """Trả slot (gọi trong `finally`)."""
