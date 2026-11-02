"""Cấu hình mcp_notify (pydantic-settings). Biến môi trường theo contracts §8.

Kế thừa `CommonSettings` (có sẵn `<BIẾN>_FILE`, `mcp_*`, `audit_hmac_key*`); ở đây chỉ thêm/đổi mặc định
riêng của notify-mcp.
"""

from acme_common.settings import CommonSettings


class Settings(CommonSettings):
    mcp_audience: str = "notify-mcp"
    mcp_port: int = 8103
    mcp_public_url: str = ""
    mcp_allowed_azp: str = "agent-service"
    mcp_rl_capacity: int = 30
    mcp_max_output_bytes: int = 16384
    mcp_database_url: str | None = None  # role nt_app; KHÔNG phải mcp_audit_database_url

    # --- intent (IntentIssuer es256_jws): khoá riêng của notify-mcp ---
    intent_private_key_path: str = ""
    intent_key_id: str = "notify-mcp-1"
    intent_ttl_s: int = 300
    intent_audience: str = "approval-signer"
    # --- approval (ApprovalVerifier es256_jwt) ---
    approval_public_key_path: str = ""
    approval_key_id: str = "ap-1"
    approval_max_ttl_s: int = 120
    replay_ttl_s: int = 180

    # --- kênh ---
    notify_channels_file: str = ""  # YAML khai báo kênh (channels.py)
    telegram_bot_token: str | None = None  # TELEGRAM_BOT_TOKEN hoặc TELEGRAM_BOT_TOKEN_FILE
    telegram_api_base: str = "https://api.telegram.org"
    message_retry_attempts: int = 3
    message_retry_max_wait_s: float = 5.0

    # --- chọn adapter (tên trong registry của factory.py) ---
    intent_issuer: str = "es256_jws"
    approval_verifier: str = "es256_jwt"
    replay_guard: str = "redis"
    delivery_log: str = "postgres"
