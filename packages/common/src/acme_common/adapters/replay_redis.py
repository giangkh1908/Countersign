"""Adapter `redis` cho port `ReplayGuard`: `SET {prefix}{jti} 1 NX EX ttl` (tickets: `mcp:tickets:jti:`)."""

from __future__ import annotations

from typing import Any

from redis.exceptions import RedisError

from ..ports import BackendUnavailable, ReplayGuard


class RedisReplayGuard(ReplayGuard):
    def __init__(self, redis: Any, *, prefix: str) -> None:
        self._r = redis
        self._prefix = prefix

    async def consume(self, jti: str, ttl_s: int) -> bool:
        try:
            return bool(await self._r.set(self._prefix + jti, "1", nx=True, ex=ttl_s))
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
