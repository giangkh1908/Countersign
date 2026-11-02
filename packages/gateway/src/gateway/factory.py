"""Factory của gateway: chọn adapter theo config bằng registry dict + lazy import.

Quy tắc (contracts §9.1 mục 5): KHÔNG dùng chuỗi if/elif. Mỗi vendor có một hàm loader
import lười (`from .adapters.<vendor> import ...` nằm TRONG hàm). Tên lạ -> raise
`XxxNotConfigured` kèm `sorted(_REGISTRY)`. Chưa có decorator cross-cutting (retry, breaker, fallback).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from acme_common.ports import Clock

from .ports.chat_provider import ChatProvider
from .ports.embedding_provider import EmbeddingProvider
from .ports.errors import (
    EmbeddingNotConfigured,
    KeyStoreNotConfigured,
    ProviderNotConfigured,
    RerankNotConfigured,
)
from .ports.key_store import KeyStore
from .ports.rerank_provider import RerankProvider
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


# --- EmbeddingProvider ---


def _load_mock_hash(settings: Settings, options: Mapping[str, Any]) -> EmbeddingProvider:
    from .adapters.mock_hash import MockHashEmbeddingProvider

    return MockHashEmbeddingProvider(int(options.get("dim", 1024)))


def _load_openai_compatible(settings: Settings, options: Mapping[str, Any]) -> EmbeddingProvider:
    from acme_common.http import RetryingHttpClient

    from .adapters.openai_compatible import OpenAICompatibleEmbeddingProvider

    base_url = options.get("base_url")
    if not base_url:
        raise EmbeddingNotConfigured("embedding adapter 'openai_compatible' requires 'base_url'")
    http = RetryingHttpClient(
        timeout_s=float(options.get("timeout_s", 30)),
        max_attempts=int(
            options.get("max_attempts", 3)
        ),  # runtime chậm: đặt 1 để timeout không nhân tải
    )
    return OpenAICompatibleEmbeddingProvider(
        base_url=str(base_url), api_key=settings.gw_embedding_api_key, http=http
    )


_EMBEDDINGS: dict[str, Callable[[Settings, Mapping[str, Any]], EmbeddingProvider]] = {
    "mock_hash": _load_mock_hash,
    "openai_compatible": _load_openai_compatible,
}


def build_embedding_provider(
    name: str, settings: Settings, options: Mapping[str, Any] | None = None
) -> EmbeddingProvider:
    """`options`: phần block alias trong models.yaml (dim, base_url, timeout_s...)."""
    try:
        loader = _EMBEDDINGS[name]
    except KeyError:
        raise EmbeddingNotConfigured(
            f"unknown embedding provider {name!r}; known: {sorted(_EMBEDDINGS)}"
        ) from None
    return loader(settings, options or {})


class EmbeddingPool:
    """Cache một instance `EmbeddingProvider` cho mỗi alias embedding."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._items: dict[str, EmbeddingProvider] = {}

    def get(self, alias: str, adapter: str, options: Mapping[str, Any]) -> EmbeddingProvider:
        if alias not in self._items:
            self._items[alias] = build_embedding_provider(adapter, self._settings, {**options})
        return self._items[alias]

    async def aclose(self) -> None:
        for p in self._items.values():
            await p.aclose()
        self._items.clear()


# --- RerankProvider ---


def _load_http_rerank(settings: Settings, options: Mapping[str, Any]) -> RerankProvider:
    from acme_common.http import RetryingHttpClient

    from .adapters.http_rerank import HttpRerankProvider

    base_url = options.get("base_url")
    if not base_url:
        raise RerankNotConfigured("rerank adapter 'http_rerank' requires 'base_url'")
    http = RetryingHttpClient(
        timeout_s=float(options.get("timeout_s", 30)),
        max_attempts=int(options.get("max_attempts", 1)),  # runtime cục bộ chậm: không nhân tải
    )
    return HttpRerankProvider(
        base_url=str(base_url),
        api_key=settings.gw_rerank_api_key,
        http=http,
        path=str(options.get("path", "/v1/rerank")),
    )


_RERANKERS: dict[str, Callable[[Settings, Mapping[str, Any]], RerankProvider]] = {
    "http_rerank": _load_http_rerank,
}


def build_rerank_provider(
    name: str, settings: Settings, options: Mapping[str, Any] | None = None
) -> RerankProvider:
    """`options`: phần block alias trong models.yaml (base_url, timeout_s, max_attempts, path)."""
    try:
        loader = _RERANKERS[name]
    except KeyError:
        raise RerankNotConfigured(
            f"unknown rerank provider {name!r}; known: {sorted(_RERANKERS)}"
        ) from None
    return loader(settings, options or {})


class RerankPool:
    """Cache một instance `RerankProvider` cho mỗi alias rerank."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._items: dict[str, RerankProvider] = {}

    def get(self, alias: str, adapter: str, options: Mapping[str, Any]) -> RerankProvider:
        if alias not in self._items:
            self._items[alias] = build_rerank_provider(adapter, self._settings, {**options})
        return self._items[alias]

    async def aclose(self) -> None:
        for p in self._items.values():
            await p.aclose()
        self._items.clear()


# --- KeyStore ---


def _load_postgres(settings: Settings, clock: Clock) -> KeyStore:
    from .adapters.postgres import PostgresKeyStore

    if not settings.gw_database_url:
        raise KeyStoreNotConfigured("key store 'postgres' requires GW_DATABASE_URL")
    return PostgresKeyStore(settings.gw_database_url, clock)


_KEY_STORES: dict[str, Callable[[Settings, Clock], KeyStore]] = {
    "postgres": _load_postgres,
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
