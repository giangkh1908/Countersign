"""Container phụ thuộc của gateway: dựng từ `Settings` qua các factory (không có tên vendor ở đây)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acme_common.factory import build_clock, build_event_sink, build_token_verifier
from acme_common.ports import Clock, EventSink, TokenVerifier

from .factory import (
    EmbeddingPool,
    ProviderPool,
    RerankPool,
    build_key_store,
    build_response_cache,
)
from .ports.chat_provider import ChatProvider
from .ports.embedding_provider import EmbeddingProvider
from .ports.key_store import KeyStore
from .ports.rerank_provider import RerankProvider
from .ports.response_cache import ResponseCache
from .services.auth import AuthService
from .services.catalog import EmbeddingSpec, ModelCatalog, RerankSpec
from .services.chat import ChatService
from .services.embeddings import EmbeddingService
from .services.metrics import Metrics
from .services.rerank import RerankService
from .settings import Settings

log = logging.getLogger("gateway")


@dataclass(slots=True)
class Container:
    auth: AuthService
    chat: ChatService
    embeddings: EmbeddingService
    rerank: RerankService
    metrics: Metrics
    sink: EventSink
    closers: list  # list[Callable[[], Awaitable[None]]]


def models_config_path(settings: Settings) -> Path:
    if settings.gw_models_config:
        return Path(settings.gw_models_config)
    local = Path("config/models.yaml")
    if local.is_file():
        return local
    return Path(__file__).resolve().parents[2] / "config" / "models.yaml"  # checkout dev


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    keys: KeyStore | None = None,
    verifier: TokenVerifier | None = None,
    sink: EventSink | None = None,
    providers: Callable[[str], ChatProvider] | None = None,
    embedders: Callable[[EmbeddingSpec], EmbeddingProvider] | None = None,
    rerankers: Callable[[RerankSpec], RerankProvider] | None = None,
    cache: ResponseCache | None = None,
) -> Container:
    clock = clock or build_clock(settings.clock_adapter, settings)
    keys = keys or build_key_store(settings.gw_keystore_adapter, settings, clock=clock)
    verifier = verifier or build_token_verifier(
        settings.token_verifier_adapter, settings, clock=clock
    )
    sink = sink or build_event_sink(settings.event_sink_adapter, settings)
    if settings.gw_provider_override:
        log.warning(
            "GW_PROVIDER_OVERRIDE=%s: MỌI alias dùng provider này, không phải provider thật",
            settings.gw_provider_override,
        )
    catalog = ModelCatalog.from_file(models_config_path(settings), settings.gw_provider_override)
    pool = ProviderPool(settings)
    providers = providers or pool.get
    embed_pool = EmbeddingPool(settings)
    embedders = embedders or (
        lambda spec: embed_pool.get(spec.alias, spec.adapter, {**spec.options, "dim": spec.dim})
    )
    rerank_pool = RerankPool(settings)
    rerankers = rerankers or (lambda spec: rerank_pool.get(spec.alias, spec.adapter, spec.options))
    metrics = Metrics()
    cache = cache or build_response_cache(settings.gw_cache_adapter, settings)
    closers = [pool.aclose, embed_pool.aclose, rerank_pool.aclose, keys.aclose]
    if cache is not None:
        closers.append(cache.aclose)
    return Container(
        auth=AuthService(keys, verifier, clock, settings.key_pepper, settings.key_pepper_prev),
        chat=ChatService(
            catalog,
            providers,
            sink,
            clock,
            metrics,
            cache=cache,
            cache_ttl_s=settings.gw_cache_ttl_s,
            cache_index_version=settings.gw_cache_index_version,
        ),
        embeddings=EmbeddingService(catalog, embedders, sink, clock, metrics),
        rerank=RerankService(catalog, rerankers, sink, clock, metrics),
        metrics=metrics,
        sink=sink,
        closers=closers,
    )
