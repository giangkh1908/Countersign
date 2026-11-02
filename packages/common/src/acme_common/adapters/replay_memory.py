"""Adapter `in_memory` cho port `ReplayGuard` (một tiến trình; dùng cho dev/test, hết hạn theo Clock)."""

from __future__ import annotations

from acme_common.ports import Clock

from ..ports import ReplayGuard


class InMemoryReplayGuard(ReplayGuard):
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._seen: dict[str, float] = {}

    async def consume(self, jti: str, ttl_s: int) -> bool:
        now = self._clock.monotonic()
        self._seen = {k: t for k, t in self._seen.items() if t > now}
        if jti in self._seen:
            return False
        self._seen[jti] = now + ttl_s
        return True
