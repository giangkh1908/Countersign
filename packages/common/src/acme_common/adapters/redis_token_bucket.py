"""Adapter `redis_token_bucket` cho port `RateLimiter`.
Milestone: M1.
Tài liệu: docs/design/00-contracts.md §9.2.
"""

from __future__ import annotations

from ..ports.rate_limiter import RateLimiter
from ..ports.types import LimitDecision


class RedisTokenBucketRateLimiter(RateLimiter):
    """Stub: hiện thực ở M2 (Lua token bucket + concurrency.lua)."""

    async def reserve(
        self, key: str, cost: int, *, limit: int, window_s: float = 60.0
    ) -> LimitDecision:
        raise NotImplementedError("redis token bucket: M2")

    async def settle(self, key: str, reserved: int, actual: int) -> None:
        raise NotImplementedError("redis token bucket: M2")

    async def acquire_slot(self, key_id: str, max_slots: int) -> LimitDecision:
        raise NotImplementedError("redis token bucket: M2")

    async def release_slot(self, key_id: str) -> None:
        raise NotImplementedError("redis token bucket: M2")
