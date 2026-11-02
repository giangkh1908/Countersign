import pytest
from mcp_docs import factory
from mcp_docs.adapters.fake_hash import FakeHashEmbedder
from mcp_docs.adapters.markdown import MarkdownLoader
from mcp_docs.adapters.none import NoReranker
from mcp_docs.ports import (
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
)
from mcp_docs.settings import Settings

S = Settings(
    mcp_database_url="postgresql://kn_app@localhost:1/knowledge",
    docs_ingest_database_url="postgresql://kn_ingest@localhost:1/knowledge",
)


def test_known_names_build_ports() -> None:
    emb = factory.build_embedder("fake_hash", S)
    assert isinstance(emb, FakeHashEmbedder) and isinstance(emb, Embedder) and emb.dim == 1024
    assert isinstance(factory.build_embedder("gateway_http", S), Embedder)
    assert isinstance(factory.build_reranker("none", S), NoReranker)
    assert isinstance(factory.build_reranker("none", S), Reranker)
    assert isinstance(factory.build_loader("a/b/x.md", S), MarkdownLoader)
    assert isinstance(factory.build_loader(".md", S), DocumentLoader)
    r = factory.build_retriever("pgvector_hybrid", S, embedder=emb)
    assert isinstance(r, DocumentRetriever)
    assert isinstance(factory.build_indexer("pgvector_hybrid", S), DocumentIndexer)
    assert isinstance(factory.build_article_reader("pgvector_hybrid", S), ArticleReader)


@pytest.mark.parametrize(
    ("call", "err"),
    [
        (lambda: factory.build_embedder("nope", S), EmbedderNotConfigured),
        (lambda: factory.build_reranker("nope", S), RerankerNotConfigured),
        (lambda: factory.build_loader("x.pdf", S), DocumentLoaderNotConfigured),
        (
            lambda: factory.build_retriever("nope", S, embedder=FakeHashEmbedder()),
            RetrieverNotConfigured,
        ),
        (lambda: factory.build_indexer("nope", S), DocumentIndexerNotConfigured),
        (lambda: factory.build_article_reader("nope", S), ArticleReaderNotConfigured),
    ],
)
def test_unknown_name_lists_known(call, err) -> None:
    with pytest.raises(err, match="known: "):
        call()


def test_retriever_requires_dsn() -> None:
    with pytest.raises(RetrieverNotConfigured):
        factory.build_retriever("pgvector_hybrid", Settings(), embedder=FakeHashEmbedder())


def test_retriever_rejects_both_branches_off() -> None:
    off = S.model_copy(update={"docs_use_vector": False, "docs_use_fts": False})
    with pytest.raises(RetrieverNotConfigured):
        factory.build_retriever("pgvector_hybrid", off, embedder=FakeHashEmbedder())
    bad = S.model_copy(update={"docs_fts_mode": "bm25"})
    with pytest.raises(RetrieverNotConfigured):
        factory.build_retriever("pgvector_hybrid", bad, embedder=FakeHashEmbedder())
