"""Decorator `CachingTokenBroker` (cùng port `TokenBroker`), contracts §2 và §9.2, ADR-005.

Khoá `(sub, sid, audience, sorted scopes)`; TTL = `min(exp token đổi, exp subject) − skew`
(token đổi ra không sống lâu hơn token người dùng). Cache trong tiến trình, single-flight theo khoá.
Khoá cache không chứa token người dùng.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from .ports.clock import Clock
from .ports.token_broker import TokenBroker
from .ports.types import AccessToken, Principal

_Key = tuple[str, str | None, str, tuple[str, ...]]


class CachingTokenBroker(TokenBroker):
    def __init__(
        self,
        inner: TokenBroker,
        clock: Clock,
        *,
        skew_s: float = 30.0,
        max_entries: int = 1024,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._skew = skew_s
        self._max = max_entries
        self._cache: dict[_Key, tuple[AccessToken, float]] = {}  # token, hạn dùng (epoch)
        self._locks: dict[_Key, asyncio.Lock] = {}

    def _get(self, key: _Key) -> AccessToken | None:
        hit = self._cache.get(key)
        if hit is None:
            return None
        if hit[1] <= self._clock.now().timestamp():
            del self._cache[key]
            return None
        return hit[0]

    def _prune(self) -> None:
        now = self._clock.now().timestamp()
        for k in [k for k, (_, ttl) in self._cache.items() if ttl <= now]:
            del self._cache[k]
        while len(self._cache) >= self._max:
            del self._cache[next(iter(self._cache))]
        for k in [k for k, lk in self._locks.items() if not lk.locked() and k not in self._cache]:
            del self._locks[k]

    async def token_for(
        self,
        principal: Principal,
        user_token: str,
        audience: str,
        scopes: Sequence[str],
    ) -> AccessToken:
        key: _Key = (principal.sub, principal.sid, audience, tuple(sorted(set(scopes))))
        if (tok := self._get(key)) is not None:
            return tok
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if (tok := self._get(key)) is not None:
                return tok
            tok = await self._inner.token_for(principal, user_token, audience, scopes)
            valid_until = min(tok.expires_at, principal.expires_at) - self._skew
            if valid_until > self._clock.now().timestamp():
                self._prune()
                self._cache[key] = (tok, valid_until)
            return tok
