"""Ports của docs-mcp (abc.ABC theo năng lực). Không import vendor."""

from .article_reader import ArticleReader
from .document_indexer import DocumentIndexer, IndexedChunk
from .document_loader import DocumentLoader
from .document_retriever import DocumentRetriever
from .embedder import Embedder
from .errors import (
    ArticleReaderNotConfigured,
    DocumentIndexerNotConfigured,
    DocumentLoaderNotConfigured,
    EmbedderNotConfigured,
    RerankerNotConfigured,
    RetrieverNotConfigured,
    SegmenterNotConfigured,
)
from .reranker import Reranker
from .text_segmenter import TextSegmenter
from .types import (
    ArticleUnit,
    Chunk,
    Document,
    DocumentMeta,
    DocumentRejected,
    EmbeddingUnavailable,
    IndexConfigError,
    Ref,
    RetrievalUnavailable,
    RetrievedChunk,
    SearchResult,
    Section,
)

__all__ = [
    "ArticleReader",
    "ArticleReaderNotConfigured",
    "ArticleUnit",
    "Chunk",
    "Document",
    "DocumentIndexer",
    "DocumentIndexerNotConfigured",
    "DocumentLoader",
    "DocumentLoaderNotConfigured",
    "DocumentMeta",
    "DocumentRejected",
    "DocumentRetriever",
    "Embedder",
    "EmbedderNotConfigured",
    "EmbeddingUnavailable",
    "IndexConfigError",
    "IndexedChunk",
    "Ref",
    "Reranker",
    "RerankerNotConfigured",
    "RetrievalUnavailable",
    "RetrievedChunk",
    "RetrieverNotConfigured",
    "SearchResult",
    "Section",
    "SegmenterNotConfigured",
    "TextSegmenter",
]
