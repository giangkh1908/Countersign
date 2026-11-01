"""Factory của mcp_docs: chọn adapter theo Settings (contracts §9.1 mục 5).

Registry dict + lazy import (import adapter bên trong loader), KHÔNG dùng chuỗi if/elif.
Tên lạ -> raise XxxNotConfigured kèm danh sách tên hợp lệ. ToolServerHost lấy từ
`acme_common.factory.build_tool_server_host`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from acme_common.factory import build_http_client, lookup

from .ports import (
    DocumentIndexer,
    DocumentIndexerNotConfigured,
    DocumentLoader,
    DocumentLoaderNotConfigured,
    DocumentRetriever,
    Embedder,
    EmbedderNotConfigured,
    Reranker,
    RerankerNotConfigured,
    RetrieverNotConfigured,
)
from .settings import Settings


# --- Embedder ---
def _load_fake_hash(s: Settings) -> Embedder:
    from .adapters.fake_hash import FakeHashEmbedder

    return FakeHashEmbedder(dim=s.docs_embed_dim)


def _load_gateway_http(s: Settings) -> Embedder:
    from .adapters.gateway_http import GatewayHttpEmbedder

    return GatewayHttpEmbedder(
        base_url=s.docs_gateway_url,
        api_key=s.docs_gateway_key,
        http=build_http_client(s),
        model=s.docs_embed_model,
        dim=s.docs_embed_dim,
    )


_EMBEDDERS: dict[str, Callable[[Settings], Embedder]] = {
    "fake_hash": _load_fake_hash,
    "gateway_http": _load_gateway_http,
}


def build_embedder(name: str, settings: Settings) -> Embedder:
    return lookup(_EMBEDDERS, name, EmbedderNotConfigured)(settings)


# --- Reranker ---
def _load_none_reranker(s: Settings) -> Reranker:
    from .adapters.none import NoReranker

    return NoReranker()


_RERANKERS: dict[str, Callable[[Settings], Reranker]] = {"none": _load_none_reranker}


def build_reranker(name: str, settings: Settings) -> Reranker:
    return lookup(_RERANKERS, name, RerankerNotConfigured)(settings)


# --- DocumentLoader (registry theo đuôi file) ---
def _load_markdown(s: Settings) -> DocumentLoader:
    from .adapters.markdown import MarkdownLoader

    return MarkdownLoader()


_LOADERS: dict[str, Callable[[Settings], DocumentLoader]] = {
    ".md": _load_markdown,
    ".markdown": _load_markdown,
}


def build_loader(path: str | Path, settings: Settings) -> DocumentLoader:
    """`path` là đường dẫn hoặc đuôi file (`.md`)."""
    text = str(path)
    ext = (
        text if text.startswith(".") and "/" not in text and "\\" not in text else Path(text).suffix
    ).lower()
    return lookup(_LOADERS, ext, DocumentLoaderNotConfigured)(settings)


# --- DocumentRetriever / DocumentIndexer ---
def _load_pg_retriever(s: Settings, embedder: Embedder) -> DocumentRetriever:
    from .adapters.pgvector_hybrid import PgVectorHybridRetriever

    if not s.mcp_database_url:
        raise RetrieverNotConfigured("MCP_DATABASE_URL is required for this retriever")
    return PgVectorHybridRetriever(
        s.mcp_database_url, embedder, rrf_k=s.docs_rrf_k, n_cand=s.docs_n_cand
    )


_RETRIEVERS: dict[str, Callable[[Settings, Embedder], DocumentRetriever]] = {
    "pgvector_hybrid": _load_pg_retriever,
}


def build_retriever(name: str, settings: Settings, *, embedder: Embedder) -> DocumentRetriever:
    return lookup(_RETRIEVERS, name, RetrieverNotConfigured)(settings, embedder)


def _load_pg_indexer(s: Settings) -> DocumentIndexer:
    from .adapters.pgvector_indexer import PgVectorIndexer

    if not s.docs_ingest_database_url:
        raise DocumentIndexerNotConfigured("DOCS_INGEST_DATABASE_URL is required for ingest")
    return PgVectorIndexer(s.docs_ingest_database_url, dim=s.docs_embed_dim)


_INDEXERS: dict[str, Callable[[Settings], DocumentIndexer]] = {
    "pgvector_hybrid": _load_pg_indexer,
}


def build_indexer(name: str, settings: Settings) -> DocumentIndexer:
    return lookup(_INDEXERS, name, DocumentIndexerNotConfigured)(settings)
