"""Cấu hình mcp_tickets (pydantic-settings). Biến môi trường theo contracts §7.

Kế thừa `CommonSettings` (có sẵn `<BIẾN>_FILE`, `mcp_*`, `audit_hmac_key*`, ...); ở đây chỉ thêm/đổi
mặc định những gì riêng của tickets-mcp.
"""

from acme_common.settings import CommonSettings


class Settings(CommonSettings):
    mcp_audience: str = "tickets-mcp"
    mcp_port: int = 8102
    mcp_public_url: str = ""
    mcp_allowed_azp: str = "agent-service"
    mcp_rl_capacity: int = 60
    mcp_max_output_bytes: int = 65536
    mcp_database_url: str | None = None  # role tk_app (RLS); KHÔNG phải mcp_audit_database_url

    # --- intent (IntentIssuer es256_jws) ---
    intent_private_key_path: str = ""
    intent_key_id: str = "tickets-mcp-1"
    intent_ttl_s: int = 300
    intent_audience: str = "approval-signer"
    # --- approval (ApprovalVerifier es256_jwt) ---
    approval_public_key_path: str = ""  # file PEM (kid = approval_key_id) hoặc thư mục <kid>.pem
    approval_key_id: str = "ap-1"
    approval_max_ttl_s: int = 120
    # --- chính sách ---
    taint_policy: str = "warn"  # warn | block
    # --- chọn adapter ---
    tickets_repository: str = "postgres"
    intent_issuer: str = "es256_jws"
    approval_verifier: str = "es256_jwt"
    replay_guard: str = "redis"
    replay_ttl_s: int = 180
