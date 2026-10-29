"""Cấu hình mcp_docs (pydantic-settings). Biến môi trường theo contracts §7."""

from acme_common.settings import CommonSettings

# TODO: hỗ trợ <BIẾN>_FILE (đọc secret từ file, _FILE thắng) theo contracts §7.


class Settings(CommonSettings):
    # Biến chung (ACME_ENV, LOG_LEVEL, ...) kế thừa từ CommonSettings.

    mcp_host: str = "mcp_sdk"
    mcp_public_url: str = ""
    mcp_database_url: str | None = None
    mcp_redis_url: str | None = None
    mcp_allowed_azp: str = "agent-service"
    mcp_allowed_origins: str = ""
    mcp_rl_capacity: int = 60
    mcp_rl_refill_per_s: float = 1.0
    mcp_max_output_bytes: int = 65536
    mcp_audit_database_url: str | None = None
    audit_hmac_key: str | None = None
    audit_hmac_key_id: str = "dev-1"
    taint_recent_ttl_s: int = 86400
    mcp_audience: str = "docs-mcp"
    mcp_port: int = 8101
    docs_gateway_url: str = "http://gateway:8000/v1"
    docs_gateway_key: str | None = None
    docs_rerank: str = "none"
    docs_retriever: str = "pgvector_hybrid"
