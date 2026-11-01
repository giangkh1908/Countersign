"""Adapter `in_memory` cho port `RateLimiter`. Degraded mode.
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ports.clock import Clock
from ..ports.rate_limiter import RateLimiter
from ..ports.types import LimitDecision


@dataclass
class _Bucket:
    capacity: float
    rate: float  # token/giây
    tokens: float
    updated: float


class InMemoryRateLimiter(RateLimiter):
    """Token bucket + đếm slot trong tiến trình (một event loop, không cần khoá)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._slots: dict[str, int] = {}

    def _bucket(self, key: str, limit: int, window_s: float) -> _Bucket:
        now = self._clock.monotonic()
        b = self._buckets.get(key)
        if b is None or b.capacity != limit:
            b = _Bucket(float(limit), limit / window_s, float(limit), now)
            self._buckets[key] = b
        else:
            b.tokens = min(b.capacity, b.tokens + (now - b.updated) * b.rate)
            b.updated = now
        return b

    async def reserve(
        self, key: str, cost: int, *, limit: int, window_s: float = 60.0
    ) -> LimitDecision:
        b = self._bucket(key, limit, window_s)
        if cost > b.capacity:
            return LimitDecision(False, b.tokens, window_s)
        if b.tokens >= cost:
            b.tokens -= cost
            return LimitDecision(True, b.tokens)
        return LimitDecision(False, b.tokens, (cost - b.tokens) / b.rate)

    async def settle(self, key: str, reserved: int, actual: int) -> None:
        b = self._buckets.get(key)
        if b is None:
            return
        b.tokens = max(0.0, min(b.capacity, b.tokens + reserved - actual))

    async def acquire_slot(self, key_id: str, max_slots: int) -> LimitDecision:
        used = self._slots.get(key_id, 0)
        if used >= max_slots:
            return LimitDecision(False, 0.0, 1.0)
        self._slots[key_id] = used + 1
        return LimitDecision(True, float(max_slots - used - 1))

    async def release_slot(self, key_id: str) -> None:
        used = self._slots.get(key_id, 0)
        if used <= 1:
            self._slots.pop(key_id, None)
        else:
            self._slots[key_id] = used - 1
