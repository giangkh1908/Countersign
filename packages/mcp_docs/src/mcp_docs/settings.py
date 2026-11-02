"""Cấu hình mcp_docs (pydantic-settings). Biến môi trường theo contracts §8."""

from acme_common.settings import CommonSettings


class Settings(CommonSettings):
    # Biến chung (ACME_ENV, LOG_LEVEL, ...) kế thừa từ CommonSettings.

    mcp_public_url: str = ""
    mcp_database_url: str | None = None
    mcp_rl_capacity: int = 60
    mcp_rl_refill_per_s: float = 1.0
    mcp_max_output_bytes: int = 65536
    mcp_audience: str = "docs-mcp"
    mcp_allowed_azp: str = "agent-service"
    mcp_allowed_hosts: str = "docs-mcp:8101,localhost:8101,127.0.0.1:8101"
    mcp_port: int = 8101
    token_required_claims: str = "sub,dept,clearance"
    forget_allowed_azp: str = "agent-service,agent-maintenance"
    docs_gateway_url: str = "http://gateway:8000/v1"
    docs_gateway_key: str | None = None
    docs_rerank: str = "none"
    docs_retriever: str = "pgvector_hybrid"
    docs_indexer: str = "pgvector_hybrid"
    docs_embedder: str = "fake_hash"  # gateway chưa có /v1/embeddings (R1); "gateway_http" khi có
    docs_embed_model: str = "acme-embed"
    docs_embed_dim: int = 1024  # khớp chunks.embedding vector(1024)
    docs_rrf_k: int = 60
    docs_n_cand: int | None = None  # None => max(50, 5*top_k)
    docs_ingest_database_url: str | None = None  # role kn_ingest (chỉ job ingest)
    docs_corpus_dir: str = "data/generated"
    docs_article_max_tokens: int = 600  # Điều <= ngưỡng này là một chunk
    docs_max_per_doc: int = 2
    docs_audit_sink: str | None = (
        None  # None: "postgres" nếu có MCP_AUDIT_DATABASE_URL, ngược lại event_sink_adapter
    )
