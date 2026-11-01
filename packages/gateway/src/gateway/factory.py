"""Factory của gateway: chọn adapter theo config bằng registry dict + lazy import.

Quy tắc (contracts §9.1 mục 5): KHÔNG dùng chuỗi if/elif. Mỗi vendor có một hàm loader
import lười (`from .adapters.<vendor> import ...` nằm TRONG hàm). Tên lạ -> raise
`XxxNotConfigured` kèm `sorted(_REGISTRY)`. Chưa có decorator cross-cutting (retry, breaker, fallback).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from acme_common.ports import Clock

from .ports.chat_provider import ChatProvider
from .ports.errors import KeyStoreNotConfigured, ProviderNotConfigured
from .ports.key_store import KeyStore
from .settings import Settings

# --- ChatProvider ---


def _load_anthropic(settings: Settings) -> ChatProvider:
    from .adapters.anthropic import AnthropicChatProvider

    if not settings.anthropic_api_key:
        raise ProviderNotConfigured("provider 'anthropic' requires ANTHROPIC_API_KEY")
    return AnthropicChatProvider(
        settings.anthropic_api_key,
        base_url=settings.gw_anthropic_base_url,
        timeout_s=settings.gw_provider_timeout_s,
    )


def _load_mock(settings: Settings) -> ChatProvider:
    from .adapters.mock import MockChatProvider

    return MockChatProvider(settings.gw_mock_base_url, timeout_s=settings.gw_provider_timeout_s)


_PROVIDERS: dict[str, Callable[[Settings], ChatProvider]] = {
    "anthropic": _load_anthropic,
    "mock": _load_mock,
}


def build_provider(name: str, settings: Settings) -> ChatProvider:
    try:
        loader = _PROVIDERS[name]
    except KeyError:
        raise ProviderNotConfigured(
            f"unknown provider {name!r}; known: {sorted(_PROVIDERS)}"
        ) from None
    return loader(settings)


# --- KeyStore ---


def _load_pg_redis_cached(settings: Settings, clock: Clock) -> KeyStore:
    from .adapters.pg_redis_cached import PgRedisCachedKeyStore

    if not settings.gw_database_url:
        raise KeyStoreNotConfigured("key store 'pg_redis_cached' requires GW_DATABASE_URL")
    return PgRedisCachedKeyStore(settings.gw_database_url, clock)


_KEY_STORES: dict[str, Callable[[Settings, Clock], KeyStore]] = {
    "pg_redis_cached": _load_pg_redis_cached,
}


def build_key_store(name: str, settings: Settings, *, clock: Clock) -> KeyStore:
    try:
        loader = _KEY_STORES[name]
    except KeyError:
        raise KeyStoreNotConfigured(
            f"unknown key store {name!r}; known: {sorted(_KEY_STORES)}"
        ) from None
    return loader(settings, clock)


class ProviderPool:
    """Cache một instance `ChatProvider` cho mỗi tên (mỗi vendor một client HTTP dùng chung)."""

    def __init__(self, settings: Settings, build: Callable[[str, Settings], Any] = build_provider):
        self._settings = settings
        self._build = build
        self._items: dict[str, ChatProvider] = {}

    def get(self, name: str) -> ChatProvider:
        if name not in self._items:
            self._items[name] = self._build(name, self._settings)
        return self._items[name]

    async def aclose(self) -> None:
        for p in self._items.values():
            await p.aclose()
        self._items.clear()
