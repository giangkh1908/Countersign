"""Cấu hình chung mọi service (contracts §7 mục "Chung")."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    acme_env: Literal["dev", "test", "bench", "eval"] = "dev"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str | None = None
    keycloak_issuer: str = "http://keycloak.acme.local:8080/realms/acme"
    metrics_token: str | None = None  # TODO: hỗ trợ METRICS_TOKEN_FILE
