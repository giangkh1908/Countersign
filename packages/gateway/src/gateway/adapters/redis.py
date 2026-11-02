"""Adapter `ResponseCache` trên Redis (service `redis-cache`: không persistence, `allkeys-lru`, ACL riêng).

Lỗi hạ tầng được ném lên để `ChatService` coi là miss và đếm metric; không log URL hay giá trị.
"""

from __future__ import annotations

import json

from redis.asyncio import Redis

from ..ports.response_cache import CachedResponse, ResponseCache


class RedisResponseCache(ResponseCache):
    def __init__(self, url: str, *, timeout_s: float = 0.3, max_value_bytes: int = 65536) -> None:
        self._redis: Redis = Redis.from_url(
            url, socket_timeout=timeout_s, socket_connect_timeout=timeout_s, decode_responses=False
        )
        self._max = max_value_bytes

    async def get(self, key: str) -> CachedResponse | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            d = json.loads(raw)
            return CachedResponse(
                content=str(d["content"]),
                finish_reason=str(d["finish_reason"]),
                prompt_tokens=int(d["prompt_tokens"]),
                completion_tokens=int(d["completion_tokens"]),
                provider=str(d["provider"]),
                model=str(d["model"]),
            )
        except (ValueError, KeyError, TypeError):
            return None  # entry hỏng = miss

    async def put(self, key: str, value: CachedResponse, ttl_s: int) -> None:
        raw = json.dumps(
            {
                "content": value.content,
                "finish_reason": value.finish_reason,
                "prompt_tokens": value.prompt_tokens,
                "completion_tokens": value.completion_tokens,
                "provider": value.provider,
                "model": value.model,
            },
            ensure_ascii=False,
        ).encode()
        if len(raw) > self._max:
            return
        await self._redis.set(key, raw, ex=ttl_s)

    async def aclose(self) -> None:
        await self._redis.aclose()
