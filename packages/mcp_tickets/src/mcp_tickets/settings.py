"""Cấu hình mcp_tickets (pydantic-settings). Biến môi trường theo contracts §7."""

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
    mcp_audience: str = "tickets-mcp"
    mcp_port: int = 8102
    intent_private_key_path: str = ""
    intent_key_id: str = "dev-intent-1"
    intent_ttl_s: int = 300
    approval_public_key_path: str = ""
    taint_policy: str = "warn"
    tickets_repository: str = "postgres"
    intent_issuer: str = "es256_jws"
    approval_verifier: str = "es256_jwt"
    audit_anchor_dir: str = ""
