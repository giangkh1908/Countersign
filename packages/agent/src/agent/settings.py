"""Cấu hình agent (pydantic-settings). Biến môi trường theo contracts §7."""

from acme_common.settings import CommonSettings

# TODO: hỗ trợ <BIẾN>_FILE (đọc secret từ file, _FILE thắng) theo contracts §7.


class Settings(CommonSettings):
    # Biến chung (ACME_ENV, LOG_LEVEL, ...) kế thừa từ CommonSettings.

    agent_gateway_url: str = "http://gateway:8000/v1"
    agent_gateway_key: str | None = None
    agent_kc_client_id: str = "agent-service"
    agent_kc_client_secret: str | None = None
    agent_database_url: str | None = None
    agent_database_owner_url: str | None = None
    mcp_docs_url: str = "http://docs-mcp:8101/mcp"
    mcp_tickets_url: str = "http://tickets-mcp:8102/mcp"
    mcp_analytics_url: str = "http://analytics-mcp:8103/mcp"
    agent_max_tool_calls_turn: int = 8
    agent_max_turn_cost_usd: float = 0.5
    agent_recursion_limit: int = 25
    agent_conf_min: float = 0.5
    agent_checkpoint_encryption_key: str | None = None
    agent_thread_retention_days: int = 30
    langfuse_host: str = ""
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_capture_content: bool = False
