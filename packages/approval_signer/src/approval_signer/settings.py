"""Cấu hình approval_signer (pydantic-settings), biến môi trường theo contracts §7.

TODO: hỗ trợ hậu tố `<BIẾN>_FILE` cho mọi secret (đọc nội dung file, `_FILE` thắng).
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    signer_port: int = 8310
    signer_audience: str = "approval-signer"
    signer_allowed_azp: str = "chat-ui"
    approval_signer_private_key_path: str | None = None
    approval_signer_key_id: str | None = None
    intent_public_keys_dir: str | None = None
    approval_ttl_s: int = 120
