"""Rate limit theo phiên / IP. Cửa sổ cố định 60s bằng INCR + EXPIRE trên `bff:sess:*`."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from .errors import ApiError
from .session import SessionStore, sess_key

LIMITS: dict[str, int] = {"read": 120, "write": 30, "llm": 20}
MAX_STREAMS = 3
STREAMS_TTL_S = 330
LOGIN_PER_MIN = 20


class RateLimits:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    async def _hit(self, key: str, limit: int, window_s: int) -> None:
        n = await self._store.incr(key, window_s)
        if n > limit:
            retry = await self._store.ttl(key)
            raise ApiError(429, "rate_limited", True, {"Retry-After": str(retry)})

    async def check(self, sid: str, bucket: str) -> None:
        await self._hit(f"{sess_key(sid)}:rl:{bucket}", LIMITS[bucket], 60)

    async def check_login(self, ip: str) -> None:
        await self._hit(f"bff:sess:rl:login:{ip}", LOGIN_PER_MIN, 60)

    async def acquire_stream(self, sid: str) -> None:
        key = f"{sess_key(sid)}:rl:streams"
        n = await self._store.incr(key, STREAMS_TTL_S)
        if n > MAX_STREAMS:
            await self._store.decr(key)
            raise ApiError(429, "rate_limited", True, {"Retry-After": "5"})

    async def release_stream(self, sid: str) -> None:
        await self._store.decr(f"{sess_key(sid)}:rl:streams")

    @contextlib.asynccontextmanager
    async def stream_slot(self, sid: str) -> AsyncIterator[None]:
        await self.acquire_stream(sid)
        try:
            yield
        finally:
            await self.release_stream(sid)
