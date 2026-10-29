"""Cấu hình policy_sidecar (pydantic-settings), biến môi trường theo contracts §7.

TODO: hỗ trợ hậu tố `<BIẾN>_FILE` cho mọi secret (đọc nội dung file, `_FILE` thắng).
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sidecar_port: int = 8010
    sidecar_token: str | None = None  # TODO _FILE
    sidecar_token_prev: str | None = None
    models_lock_path: str = "/app/models.lock"
    models_lock_sha256: str | None = None
    sidecar_models_dir: str = "/models"
    sidecar_embed_enabled: bool = True
    sidecar_guard_enabled: bool = True
    sidecar_ner_enabled: bool = True
    sidecar_workers: int = 1
    sidecar_pool_online_guard_ner: int = 2
    sidecar_pool_embed_query: int = 2
    sidecar_pool_embed_ingest: int = 1
    sidecar_maxinflight_online_guard_ner: int = 16
    sidecar_maxinflight_embed_query: int = 16
    sidecar_maxinflight_embed_ingest: int = 4
