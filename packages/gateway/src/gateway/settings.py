"""Cấu hình gateway (pydantic-settings), biến môi trường theo contracts §8.

Hậu tố `<BIẾN>_FILE` cho mọi secret do `CommonSettings` lo (đọc nội dung file, `_FILE` thắng).
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gw_database_url: str | None = None
    gw_key_pepper: str | None = None  # >= 32 byte; GW_KEY_PEPPER hoặc GW_KEY_PEPPER_FILE
    gw_key_pepper_prev: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None  # OPENROUTER_API_KEY[_FILE]
    gw_provider_override: str | None = None  # vd "mock"; factory thay mọi chain
    gw_keystore_adapter: str = "postgres"
    gw_models_config: str | None = None  # mặc định ./config/models.yaml
    gw_mock_base_url: str = "http://mock-provider:8900"  # adapter `mock`
    gw_anthropic_base_url: str | None = None  # None = endpoint công khai của SDK
    gw_openrouter_base_url: str = (
        "https://openrouter.ai/api"  # client gọi {base}/v1/chat/completions
    )
    gw_provider_timeout_s: float = 60.0  # trần timeout HTTP tới provider
    gw_embedding_api_key: str | None = (
        None  # adapter `openai_compatible`; GW_EMBEDDING_API_KEY[_FILE]
    )
    gw_rerank_api_key: str | None = None  # adapter `http_rerank`; GW_RERANK_API_KEY[_FILE]
    # Exact cache (cache-observability.md §1). Mặc định TẮT; bật: GW_CACHE_ADAPTER=redis
    gw_cache_adapter: str = "off"
    gw_cache_redis_url: str | None = (
        None  # GW_CACHE_REDIS_URL[_FILE]; user ACL riêng của redis-cache
    )
    gw_cache_ttl_s: int = 3600
    gw_cache_timeout_s: float = 0.3  # Redis chậm/chết thì coi như miss, không kéo dài request
    gw_cache_max_value_bytes: int = 65536
    # Tăng khi nạp lại index hoặc đổi embedding: entry cũ không bao giờ trúng nữa
    gw_cache_index_version: str = "0"
    gw_max_body_bytes: int = 4 * 1024 * 1024
    gw_sink_flush_interval_s: float = 2.0  # chu kỳ đẩy buffer EventSink (usage_events)

    @property
    def key_pepper(self) -> bytes:
        if not self.gw_key_pepper:
            raise ValueError("GW_KEY_PEPPER (hoặc GW_KEY_PEPPER_FILE) chưa được đặt")
        return self.gw_key_pepper.encode()

    @property
    def key_pepper_prev(self) -> bytes | None:
        return self.gw_key_pepper_prev.encode() if self.gw_key_pepper_prev else None
