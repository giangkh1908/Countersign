"""Cấu hình approval_signer (pydantic-settings), biến môi trường theo contracts §7.

Hậu tố `<BIẾN>_FILE` do `CommonSettings` xử lý (đọc nội dung file, `_FILE` thắng). Khoá ký có hai nguồn:
`APPROVAL_SIGNER_PRIVATE_KEY_PATH` (đường dẫn PEM, đúng contracts/compose) hoặc nội dung PEM qua
`APPROVAL_SIGNER_PRIVATE_KEY_FILE`.
"""

from acme_common.settings import CommonSettings
from pydantic_settings import SettingsConfigDict


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    signer_port: int = 8310
    signer_audience: str = "approval-signer"
    signer_allowed_azp: str = "chat-ui"
    signer_required_scope: str = "signer:approve"
    signer_rl_per_hour: int = 30
    approval_signer_private_key_path: str | None = None
    approval_signer_private_key: str | None = None  # nội dung PEM, đặt qua *_PRIVATE_KEY_FILE
    approval_signer_key_id: str | None = None
    intent_public_keys_dir: str | None = None
    intent_issuer_name: str = "tickets-mcp"
    approval_ttl_s: int = 120

    # --- Chọn adapter (registry trong factory.py) ---
    intent_verifier_adapter: str = "es256_jws"
    approval_signer_adapter: str = "es256_jwt"

    @property
    def token_verifier_settings(self) -> "Settings":
        """Bản sao ép các ràng buộc D13/D15/D16 lên `TokenVerifier` dùng chung."""
        return self.model_copy(
            update={
                "token_allowed_azp": self.signer_allowed_azp,
                "token_required_scopes": self.signer_required_scope,
                "token_required_claims": "sub",
            }
        )
