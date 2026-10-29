"""Cấu hình bff (pydantic-settings). Biến môi trường theo contracts §7."""

from acme_common.settings import CommonSettings

# TODO: hỗ trợ <BIẾN>_FILE (đọc secret từ file, _FILE thắng) theo contracts §7.


class Settings(CommonSettings):
    # Biến chung (ACME_ENV, LOG_LEVEL, ...) kế thừa từ CommonSettings.

    bff_public_url: str = "http://localhost:8300"
    bff_session_key: str | None = None
    bff_oidc_client_secret: str | None = None
    bff_agent_url: str = "http://agent:8200"
    bff_signer_url: str = "http://approval-signer:8310"
    bff_redis_url: str = "redis://bff@redis-state:6379/0"
    redis_bff_password: str | None = None
    bff_signer_token_ttl_s: int = 300
    bff_session_idle_s: int = 1800
    bff_session_abs_s: int = 28800
    bff_rejected_ttl_s: int = 600
    bff_max_cards_per_thread_hour: int = 10
    bff_stream_max_s: int = 300
    bff_stream_idle_s: int = 45
    bff_link_allowlist: str = ""
    bff_gateway_url: str = ""
    bff_cookie_insecure_dev: bool = False
    bff_trusted_proxy: bool = False
    bff_static_dir: str = ""
