"""Cấu hình chung mọi service (contracts §8).

Quy ước secret (contracts §8): mọi trường có thể đặt qua `<BIẾN>_FILE` (đường dẫn file, vd Docker
secret); có cả hai thì `_FILE` thắng. Service con kế thừa `CommonSettings` là có sẵn cơ chế này.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _split(value: str) -> tuple[str, ...]:
    return tuple(p for p in (s.strip() for s in value.replace(" ", ",").split(",")) if p)


class _FileSecretsSource(PydanticBaseSettingsSource):
    """Đọc `<FIELD>_FILE` (từ môi trường hoặc `.env`) và nạp nội dung file làm giá trị trường."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # không dùng; __call__ tự duyệt

    def __call__(self) -> dict[str, Any]:
        env_file = self.config.get("env_file")
        env: dict[str, str | None] = {}
        if isinstance(env_file, str | os.PathLike) and Path(env_file).is_file():
            env.update(dotenv_values(env_file))
        env.update(os.environ)
        upper = {k.upper(): v for k, v in env.items() if v}
        out: dict[str, Any] = {}
        for name in self.settings_cls.model_fields:
            path = upper.get(f"{name.upper()}_FILE")
            if not path:
                continue
            try:
                out[name] = Path(path).read_text(encoding="utf8").strip()
            except OSError:
                raise ValueError(f"cannot read secret file for {name.upper()}") from None
        return out


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # --- Chung (contracts §8) ---
    acme_env: Literal["dev", "test", "eval"] = "dev"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str | None = None
    keycloak_issuer: str = "http://keycloak.acme.local:8080/realms/acme"
    metrics_token: str | None = None  # METRICS_TOKEN hoặc METRICS_TOKEN_FILE

    # --- IdP: URL máy-với-máy có thể khác issuer công khai (vd trong compose) ---
    oidc_jwks_url: str | None = None  # mặc định suy ra từ keycloak_issuer
    oidc_token_url: str | None = None  # mặc định suy ra từ keycloak_issuer

    # --- TokenVerifier (oidc_jwks) ---
    oidc_algorithms: str = "RS256,ES256"
    token_allowed_azp: str = ""  # rỗng = không kiểm azp; vd "agent-service" hoặc "chat-ui"
    token_required_scopes: str = ""  # vd "agent:invoke"
    token_required_claims: str = "sub"  # resource server MCP/signer: "sub,dept,clearance"
    token_leeway_s: float = 0.0
    jwks_cache_ttl_s: float = 300.0
    jwks_min_refetch_s: float = 30.0

    # --- TokenBroker (oauth_token_exchange + CachingTokenBroker) ---
    token_cache_skew_s: float = 30.0
    token_ignored_scopes: str = "openid,profile,email,offline_access,acme-claims,aud-chat-ui"

    # --- RetryingHttpClient ---
    http_timeout_s: float = 10.0
    http_max_attempts: int = 3

    # --- Chọn adapter (tên trong registry của factory) ---
    clock_adapter: str = "system"
    token_verifier_adapter: str = "oidc_jwks"
    token_broker_adapter: str = "oauth_token_exchange"
    event_sink_adapter: str = "json_log"
    rate_limiter_adapter: str = "in_memory"

    # --- EventSink postgres / audit hash-chain (contracts §5) ---
    event_sink_database_url: str | None = None  # gateway: usage_events + audit_log
    mcp_audit_database_url: str | None = None  # MCP: tool_audit (role mcp_audit_w)
    audit_hmac_key: str | None = None  # AUDIT_HMAC_KEY hoặc AUDIT_HMAC_KEY_FILE; >= 16 byte
    audit_hmac_key_id: int = 1

    # --- MCP server host ---
    mcp_host: str = "mcp_sdk"  # tên adapter ToolServerHost
    mcp_audience: str = ""
    mcp_allowed_azp: str = ""
    mcp_allowed_origins: str = ""
    mcp_allowed_hosts: str = ""  # vd "docs-mcp:8101,localhost:8101"
    mcp_rl_capacity: int = 30
    mcp_rl_refill_per_s: float = 1.0
    mcp_max_output_bytes: int = 32_768
    mcp_redis_url: str | None = None
    taint_recent_ttl_s: int = 86400
    agent_thread_retention_days: int = 30

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _FileSecretsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    # --- Giá trị suy ra ---
    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return self.oidc_token_url or f"{self.keycloak_issuer}/protocol/openid-connect/token"

    @property
    def algorithms(self) -> tuple[str, ...]:
        return _split(self.oidc_algorithms)

    @property
    def allowed_azp(self) -> frozenset[str]:
        return frozenset(_split(self.token_allowed_azp))

    @property
    def required_scopes(self) -> frozenset[str]:
        return frozenset(_split(self.token_required_scopes))

    @property
    def required_claims(self) -> tuple[str, ...]:
        return _split(self.token_required_claims)

    @property
    def mcp_allowed_azp_set(self) -> frozenset[str]:
        return frozenset(_split(self.mcp_allowed_azp))

    @property
    def mcp_allowed_hosts_set(self) -> tuple[str, ...]:
        return _split(self.mcp_allowed_hosts)

    @property
    def mcp_allowed_origins_set(self) -> frozenset[str]:
        return frozenset(_split(self.mcp_allowed_origins))

    @property
    def ignored_scopes(self) -> frozenset[str]:
        return frozenset(_split(self.token_ignored_scopes))
