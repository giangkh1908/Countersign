"""Cấu hình agent (pydantic-settings). Biến môi trường theo contracts §8.

Cơ chế `<BIẾN>_FILE` (đọc secret từ file, `_FILE` thắng) kế thừa từ `CommonSettings`.
"""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from acme_common.settings import CommonSettings
from pydantic import Field

from .ports.errors import ConfigError

# Vai trò LLM -> alias (contracts §8). Ghi đè bằng AGENT_ROLE_ALIASES='{"agent":"acme-fast"}'.
DEFAULT_ROLE_ALIASES: dict[str, str] = {
    "router": "acme-fast",
    "agent": "acme-smart",
    "final": "acme-fast",
    "direct": "acme-fast",
    "summarize": "acme-fast",
    "judge": "acme-judge",
}


class Settings(CommonSettings):
    # Biến chung (ACME_ENV, LOG_LEVEL, ...) kế thừa từ CommonSettings.

    # --- Xác thực token vào agent (BFF gửi token aud=agent-service, azp=chat-ui) ---
    agent_audience: str = "agent-service"
    token_allowed_azp: str = "chat-ui"
    token_required_scopes: str = "agent:invoke"

    # --- Gateway LLM + exchange ---
    agent_gateway_url: str = "http://gateway:8000/v1"
    agent_gateway_key: str | None = None
    agent_kc_client_id: str = "agent-service"
    agent_kc_client_secret: str | None = None
    agent_role_aliases: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_ROLE_ALIASES))

    # --- MCP ---
    mcp_docs_url: str = "http://docs-mcp:8101/mcp"
    mcp_tickets_url: str = "http://tickets-mcp:8102/mcp"  # rỗng = tắt agent ticket
    mcp_notify_url: str = "http://notify-mcp:8103/mcp"  # rỗng = tắt agent report

    # --- Giới hạn vòng lặp ---
    agent_max_tool_calls_turn: int = 8
    agent_max_react_iters: int = 6
    agent_max_turn_cost_usd: float = 0.5
    agent_recursion_limit: int = 25
    agent_conf_min: float = 0.5
    agent_max_input_chars: int = 4000

    # --- Kiểm chứng trích dẫn sau sinh (rag-citations §5.3) ---
    agent_verify_citations: Literal["on", "off"] = "on"
    agent_verify_judge_adapter: str = "gateway_llm"
    agent_verify_judge_alias: str = "acme-judge"
    agent_verify_max_concurrency: int = 4
    agent_verify_max_pairs: int = 12
    agent_verify_require_citation: bool = True
    agent_verify_on_unsupported: Literal["flag", "drop"] = "flag"
    agent_verify_min_supported_ratio: float = 0.5

    # --- Lưu trữ ---
    agent_database_url: str | None = None
    agent_database_owner_url: str | None = None  # DSN role ag_owner (chỉ job migrate)
    agent_owner_password: str | None = (
        None  # thay cho DSN: dựng từ pg_host/pg_port + mật khẩu ag_owner
    )
    pg_host: str = "postgres"
    pg_port: int = 5432
    agent_checkpoint_encryption_key: str | None = None  # base64 của 32 byte
    agent_thread_retention_days: int = 30

    # --- Chọn adapter (tên trong registry của factory.py) ---
    tool_provider_adapter: str = "mcp_http"
    conversation_repo_adapter: str = "postgres"
    checkpointer_adapter: str = "postgres"
    service_probe_adapter: str = "http"
    optional_agents_recheck_s: float = 10.0  # 0 = không dò lại sau khi khởi động
    agents_enabled: str = "docs,ticket,report"

    @property
    def mcp_servers(self) -> dict[str, str]:
        """audience -> URL endpoint MCP."""
        all_servers = {
            "docs-mcp": self.mcp_docs_url,
            "tickets-mcp": self.mcp_tickets_url,
            "notify-mcp": self.mcp_notify_url,
        }
        return {aud: url for aud, url in all_servers.items() if url}

    @property
    def enabled_agents(self) -> tuple[str, ...]:
        return tuple(p for p in (s.strip() for s in self.agents_enabled.split(",")) if p)

    def checkpoint_key_bytes(self) -> bytes | None:
        """Giải mã `AGENT_CHECKPOINT_ENCRYPTION_KEY` (ADR-004). Thiếu ngoài `ACME_ENV=test` => lỗi."""
        raw = self.agent_checkpoint_encryption_key
        if not raw:
            if self.acme_env == "test":
                return None
            raise ConfigError("AGENT_CHECKPOINT_ENCRYPTION_KEY is required outside ACME_ENV=test")
        try:
            key = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ConfigError("AGENT_CHECKPOINT_ENCRYPTION_KEY must be base64") from None
        if len(key) != 32:
            raise ConfigError("AGENT_CHECKPOINT_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return key
