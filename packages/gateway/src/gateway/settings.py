"""Cấu hình gateway (pydantic-settings), biến môi trường theo contracts §7.

TODO: hỗ trợ hậu tố `<BIẾN>_FILE` cho mọi secret (đọc nội dung file, `_FILE` thắng).
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gw_database_url: str | None = None
    gw_redis_state_url: str | None = None
    gw_redis_cache_url: str | None = None
    gw_key_pepper: str | None = None  # >= 32 byte; TODO _FILE
    gw_key_pepper_prev: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    gw_sidecar_url: str = "http://policy-sidecar:8010"
    sidecar_token: str | None = None
    sidecar_token_prev: str | None = None
    gw_sidecar_timeout_ms: int = 2000
    gw_guard_tool_fail_policy: str = "redact"
    gw_guard_user_fail_policy: str = "open"  # open|closed
    gw_ner_external_fail_policy: str = "closed"
    gw_workers: int = 1
    gw_instances: int = 1
    gw_degraded_max_s: int = 600
    audit_hmac_key: str | None = None
    audit_hmac_key_id: str | None = None
    audit_anchor_dir: str | None = None
    audit_anchor_bucket: str | None = None
    gw_provider_override: str | None = None  # vd "mock"; factory thay mọi chain
    gw_features: str = "auth,ratelimit,budget,pii,guard,cache,router"
    gw_pii_strict: bool = False
