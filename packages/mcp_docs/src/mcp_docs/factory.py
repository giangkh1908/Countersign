"""Factory của mcp_docs: chọn adapter theo Settings (contracts §9.1 mục 5).

Registry dict + lazy import (import adapter bên trong loader), KHÔNG dùng chuỗi if/elif.
Tên lạ -> raise XxxNotConfigured kèm danh sách tên hợp lệ. ToolServerHost lấy từ
`acme_common.factory.build_tool_server_host`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from acme_common.factory import lookup
from acme_common.http import RetryingHttpClient

from .ports import (
    ArticleReader,
    ArticleReaderNotConfigured,
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
    SegmenterNotConfigured,
    TextSegmenter,
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
        http=RetryingHttpClient(
            timeout_s=s.docs_embed_timeout_s, max_attempts=s.docs_embed_max_attempts
        ),
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


def _load_vbpl_articles(s: Settings) -> DocumentLoader:
    from .adapters.vbpl_articles import VbplArticlesLoader

    return VbplArticlesLoader()


_LOADERS: dict[str, Callable[[Settings], DocumentLoader]] = {
    ".md": _load_markdown,
    ".markdown": _load_markdown,
    ".json": _load_vbpl_articles,
}


def build_loader(path: str | Path, settings: Settings) -> DocumentLoader:
    """`path` là đường dẫn hoặc đuôi file (`.md`)."""
    text = str(path)
    ext = (
        text if text.startswith(".") and "/" not in text and "\\" not in text else Path(text).suffix
    ).lower()
    return lookup(_LOADERS, ext, DocumentLoaderNotConfigured)(settings)


# --- TextSegmenter ---
def _load_no_segmenter(s: Settings) -> TextSegmenter:
    from .adapters.segmenter_none import NoSegmenter

    return NoSegmenter()


def _load_syllable_bigram(s: Settings) -> TextSegmenter:
    from .adapters.segmenter_syllable_bigram import SyllableBigramSegmenter

    return SyllableBigramSegmenter()


_SEGMENTERS: dict[str, Callable[[Settings], TextSegmenter]] = {
    "none": _load_no_segmenter,
    "syllable_bigram": _load_syllable_bigram,
}


def build_segmenter(name: str, settings: Settings) -> TextSegmenter:
    return lookup(_SEGMENTERS, name, SegmenterNotConfigured)(settings)


# --- DocumentRetriever / DocumentIndexer ---
def _load_pg_retriever(s: Settings, embedder: Embedder) -> DocumentRetriever:
    from .adapters.pgvector_hybrid import PgVectorHybridRetriever

    if not s.mcp_database_url:
        raise RetrieverNotConfigured("MCP_DATABASE_URL is required for this retriever")
    if not (s.docs_use_vector or s.docs_use_fts):
        raise RetrieverNotConfigured("DOCS_USE_VECTOR and DOCS_USE_FTS are both off")
    if s.docs_fts_mode not in ("unaccent", "segmented"):
        raise RetrieverNotConfigured("DOCS_FTS_MODE must be 'unaccent' or 'segmented'")
    return PgVectorHybridRetriever(
        s.mcp_database_url,
        embedder,
        rrf_k=s.docs_rrf_k,
        n_cand=s.docs_n_cand,
        use_vector=s.docs_use_vector,
        use_fts=s.docs_use_fts,
        fts_mode=s.docs_fts_mode,
        segmenter=build_segmenter(s.docs_segmenter, s),
    )


_RETRIEVERS: dict[str, Callable[[Settings, Embedder], DocumentRetriever]] = {
    "pgvector_hybrid": _load_pg_retriever,
}


def build_retriever(name: str, settings: Settings, *, embedder: Embedder) -> DocumentRetriever:
    return lookup(_RETRIEVERS, name, RetrieverNotConfigured)(settings, embedder)


# --- ArticleReader ---
def _load_pg_article_reader(s: Settings) -> ArticleReader:
    from .adapters.pg_article_reader import PgArticleReader

    if not s.mcp_database_url:
        raise ArticleReaderNotConfigured("MCP_DATABASE_URL is required for this reader")
    return PgArticleReader(s.mcp_database_url)


_ARTICLE_READERS: dict[str, Callable[[Settings], ArticleReader]] = {
    "pgvector_hybrid": _load_pg_article_reader,
}


def build_article_reader(name: str, settings: Settings) -> ArticleReader:
    """`name` theo cùng khoá với retriever (cùng kho, cùng DSN `kn_app`)."""
    return lookup(_ARTICLE_READERS, name, ArticleReaderNotConfigured)(settings)


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
