"""`Fake<Port>` của gateway (kế thừa port). Fake của port chung nằm ở `acme_common.testing`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

from .ports.chat_provider import ChatProvider
from .ports.embedding_provider import EmbeddingProvider
from .ports.errors import KeyAlreadyExists, KeyNotFound
from .ports.key_store import KeyStore
from .ports.rerank_provider import RerankProvider
from .ports.response_cache import CachedResponse, ResponseCache
from .ports.types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingResult,
    KeyRecord,
    NewKey,
    ProviderError,
    RerankItem,
    RerankResult,
)


class FakeKeyStore(KeyStore):
    def __init__(self) -> None:
        self.records: dict[str, KeyRecord] = {}  # prefix -> record
        self.lookups: list[str] = []

    async def lookup(self, prefix: str) -> KeyRecord | None:
        self.lookups.append(prefix)
        return self.records.get(prefix)

    async def create(self, new: NewKey, actor: str) -> KeyRecord:
        if new.prefix in self.records:
            raise KeyAlreadyExists(new.prefix)
        rec = KeyRecord(
            key_id=str(uuid.uuid4()),
            prefix=new.prefix,
            secret_hmac=new.secret_hmac,
            name=new.name,
            dept=new.dept,
            allowed_models=new.allowed_models,
            rpm=new.rpm,
            tpm=new.tpm,
            max_concurrency=new.max_concurrency,
            trust_end_user_token=new.trust_end_user_token,
            expose_debug=new.expose_debug,
            status="active",
            expires_at=new.expires_at,
        )
        self.records[new.prefix] = rec
        return rec

    async def revoke(self, key_id: str, actor: str, reason: str) -> None:
        for prefix, rec in self.records.items():
            if rec.key_id == key_id and rec.status != "revoked":
                self.records[prefix] = replace(rec, status="revoked")
                return
        raise KeyNotFound(key_id)

    async def update_allowed_models(
        self, key_id: str, allowed_models: tuple[str, ...], actor: str
    ) -> None:
        for prefix, rec in self.records.items():
            if rec.key_id == key_id and rec.status == "active":
                self.records[prefix] = replace(rec, allowed_models=allowed_models)
                return
        raise KeyNotFound(key_id)


class FakeChatProvider(ChatProvider):
    """Trả kết quả dựng sẵn hoặc raise `ProviderError`; ghi lại request nhận được."""

    name = "fake"

    def __init__(
        self,
        response: ChatResponse | None = None,
        chunks: list[ChatChunk] | None = None,
        error: ProviderError | None = None,
        error_after_chunks: int | None = None,
    ) -> None:
        self.response, self.chunks, self.error = response, chunks or [], error
        self.error_after_chunks = error_after_chunks
        self.requests: list[ChatRequest] = []

    async def complete(self, req: ChatRequest) -> ChatResponse:
        self.requests.append(req)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        self.requests.append(req)
        if self.error and self.error_after_chunks is None:
            raise self.error
        for i, ch in enumerate(self.chunks):
            if self.error and i == self.error_after_chunks:
                raise self.error
            yield ch


class FakeEmbeddingProvider(EmbeddingProvider):
    """Trả vector dựng sẵn hoặc raise `ProviderError`; ghi lại lời gọi."""

    name = "fake"

    def __init__(
        self,
        vectors: list[list[float]] | None = None,
        error: ProviderError | None = None,
        cost_usd: float | None = None,
    ) -> None:
        self.vectors, self.error, self.cost_usd = vectors, error, cost_usd
        self.calls: list[tuple[str, list[str]]] = []

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        self.calls.append((model, texts))
        if self.error:
            raise self.error
        assert self.vectors is not None
        return EmbeddingResult(self.vectors, len(texts), self.cost_usd)


class FakeRerankProvider(RerankProvider):
    """Trả điểm dựng sẵn (theo thứ tự `documents`) hoặc raise `ProviderError`; ghi lại lời gọi."""

    name = "fake"

    def __init__(
        self,
        scores: list[float] | None = None,
        error: ProviderError | None = None,
        cost_usd: float | None = None,
    ) -> None:
        self.scores, self.error, self.cost_usd = scores, error, cost_usd
        self.calls: list[tuple[str, str, list[str], int]] = []

    async def rerank(
        self, model: str, query: str, documents: list[str], top_n: int
    ) -> RerankResult:
        self.calls.append((model, query, documents, top_n))
        if self.error:
            raise self.error
        assert self.scores is not None
        return RerankResult(
            [RerankItem(i, s) for i, s in enumerate(self.scores)], len(query), self.cost_usd
        )


class FakeResponseCache(ResponseCache):
    """Kho trong bộ nhớ; `fail=True` giả lập Redis chết (get/put raise)."""

    def __init__(self, fail: bool = False) -> None:
        self.items: dict[str, CachedResponse] = {}
        self.ttls: dict[str, int] = {}
        self.gets: list[str] = []
        self.fail = fail

    async def get(self, key: str) -> CachedResponse | None:
        self.gets.append(key)
        if self.fail:
            raise ConnectionError("cache down")
        return self.items.get(key)

    async def put(self, key: str, value: CachedResponse, ttl_s: int) -> None:
        if self.fail:
            raise ConnectionError("cache down")
        self.items[key] = value
        self.ttls[key] = ttl_s


def provider_lookup(**providers: ChatProvider) -> Callable[[str], ChatProvider]:
    from .ports.errors import ProviderNotConfigured

    def get(name: str) -> ChatProvider:
        try:
            return providers[name]
        except KeyError:
            raise ProviderNotConfigured(name) from None

    return get


__all__ = [
    "FakeChatProvider",
    "FakeEmbeddingProvider",
    "FakeKeyStore",
    "FakeRerankProvider",
    "FakeResponseCache",
    "provider_lookup",
]
