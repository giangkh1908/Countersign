"""Adapter `redis` cho port `ReplayGuard`: `SET mcp:tickets:jti:{jti} 1 NX EX ttl`."""

from __future__ import annotations

from typing import Any

from redis.exceptions import RedisError

from ..ports import BackendUnavailable, ReplayGuard

JTI_PREFIX = "mcp:tickets:jti:"


class RedisReplayGuard(ReplayGuard):
    def __init__(self, redis: Any) -> None:
        self._r = redis

    async def consume(self, jti: str, ttl_s: int) -> bool:
        try:
            return bool(await self._r.set(JTI_PREFIX + jti, "1", nx=True, ex=ttl_s))
        except (RedisError, OSError, TimeoutError):
            raise BackendUnavailable("redis") from None
