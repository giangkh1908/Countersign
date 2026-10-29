"""Cấu hình mock_provider (pydantic-settings), biến môi trường theo contracts §7.

TODO: hỗ trợ hậu tố `<BIẾN>_FILE` cho mọi secret (đọc nội dung file, `_FILE` thắng).
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mock_provider_port: int = 8900
