"""Cấu hình gateway (pydantic-settings), biến môi trường theo contracts §7.

Hậu tố `<BIẾN>_FILE` cho mọi secret do `CommonSettings` lo (đọc nội dung file, `_FILE` thắng).
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gw_database_url: str | None = None
    gw_redis_state_url: str | None = None
    gw_redis_cache_url: str | None = None
    gw_key_pepper: str | None = None  # >= 32 byte; GW_KEY_PEPPER hoặc GW_KEY_PEPPER_FILE
    gw_key_pepper_prev: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
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
    gw_keystore_adapter: str = "pg_redis_cached"
    gw_models_config: str | None = None  # mặc định ./config/models.yaml
    gw_mock_base_url: str = "http://mock-provider:8900"  # adapter `mock`
    gw_anthropic_base_url: str | None = None  # None = endpoint công khai của SDK
    gw_provider_timeout_s: float = 60.0  # trần timeout HTTP tới provider
    gw_max_body_bytes: int = 4 * 1024 * 1024
    gw_pii_strict: bool = False
    gw_sink_flush_interval_s: float = 2.0  # chu kỳ đẩy buffer EventSink (usage_events)

    @property
    def key_pepper(self) -> bytes:
        if not self.gw_key_pepper:
            raise ValueError("GW_KEY_PEPPER (hoặc GW_KEY_PEPPER_FILE) chưa được đặt")
        return self.gw_key_pepper.encode()

    @property
    def key_pepper_prev(self) -> bytes | None:
        return self.gw_key_pepper_prev.encode() if self.gw_key_pepper_prev else None
