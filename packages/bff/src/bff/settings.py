"""Cấu hình bff (pydantic-settings). Biến môi trường theo contracts §8.

`CommonSettings` đã hỗ trợ `<BIẾN>_FILE` (đọc secret từ file, `_FILE` thắng).
"""

from __future__ import annotations

import base64
import binascii
from urllib.parse import urlsplit

from acme_common.settings import CommonSettings


class SettingsError(ValueError):
    """Cấu hình không an toàn: bff từ chối khởi động."""


def _split_hosts(value: str) -> tuple[str, ...]:
    return tuple(p for p in (s.strip() for s in value.replace(" ", ",").split(",")) if p)


class Settings(CommonSettings):
    bff_public_url: str = "http://localhost:8300"
    bff_session_key: str | None = None
    bff_oidc_client_secret: str | None = None
    bff_oidc_client_id: str = "chat-ui"
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
    bff_stream_heartbeat_s: float = 15.0
    bff_link_allowlist: str = ""
    bff_gateway_url: str = ""
    bff_cookie_insecure_dev: bool = False
    bff_trusted_proxy: bool = False
    bff_static_dir: str = ""

    # --- Giá trị suy ra ---
    @property
    def oidc_issuer(self) -> str:
        """Issuer công khai của IdP (trung lập vendor; tên biến gốc nằm ở CommonSettings)."""
        return self.keycloak_issuer

    @property
    def https(self) -> bool:
        return self.bff_public_url.lower().startswith("https://")

    @property
    def public_origin(self) -> str:
        p = urlsplit(self.bff_public_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def link_allowlist(self) -> tuple[str, ...]:
        return _split_hosts(self.bff_link_allowlist)

    @property
    def session_key_bytes(self) -> bytes:
        raw = self.bff_session_key or ""
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (binascii.Error, ValueError):
            raise SettingsError("BFF_SESSION_KEY phải là base64 của 32 byte") from None
        if len(key) != 32:
            raise SettingsError("BFF_SESSION_KEY phải đủ 32 byte")
        return key

    def validate_runtime(self) -> None:
        """Từ chối chạy khi cấu hình không an toàn."""
        if not self.https and self.acme_env != "dev":
            raise SettingsError("BFF_PUBLIC_URL phải là https khi ACME_ENV != dev")
        _ = self.session_key_bytes
        if not self.bff_oidc_client_secret:
            raise SettingsError("thiếu BFF_OIDC_CLIENT_SECRET")
        if not 0 < self.bff_signer_token_ttl_s <= 300:
            raise SettingsError("BFF_SIGNER_TOKEN_TTL_S phải trong (0, 300]")
