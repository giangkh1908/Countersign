"""Cấu hình mock_provider (pydantic-settings), biến môi trường theo contracts §8 và docker-compose.

Mọi giá trị hành vi (`MOCK_*`) là mặc định; header `x-mock-*` theo từng request và API
`/__control` ghi đè được (header > /__control theo scope > /__control `*` > env).
"""

from pathlib import Path

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mock_provider_port: int = 8900
    mock_ttft_ms: float = 300.0
    mock_tokens_per_sec: float = 50.0  # 0 = không trễ giữa các token
    mock_output_tokens: int = 50
    mock_seed: int = 0
    mock_error_rate: float = 0.0  # xác suất lỗi ngẫu nhiên (0..1)
    mock_error_kinds: str = "429,500,503"  # tập lỗi chọn khi gặp lỗi ngẫu nhiên
    mock_retry_after_s: int = 1
    mock_hang_s: float = 3600.0  # thời gian treo của lỗi `timeout`
    mock_tool_prefix: str = "call_tool:"
    mock_required_key: str | None = None  # đặt thì key sai/thiếu -> 401
    mock_control_token: str | None = None
    mock_control_token_file: str | None = None  # `_FILE` thắng

    @property
    def control_token(self) -> str | None:
        if self.mock_control_token_file:
            return Path(self.mock_control_token_file).read_text(encoding="utf-8").strip()
        return self.mock_control_token
