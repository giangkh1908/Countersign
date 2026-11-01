"""Factory chọn adapter theo tên trong config (contracts §9.1 mục 5): registry dict + lazy import.

Tên lạ => `XxxNotConfigured` kèm danh sách tên hợp lệ. Business logic chỉ import file này và `ports`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .caching_token_broker import CachingTokenBroker
from .http import RetryingHttpClient
from .ports.clock import Clock
from .ports.errors import (
    ClockNotConfigured,
    EventSinkNotConfigured,
    NotConfigured,
    RateLimiterNotConfigured,
    TokenBrokerNotConfigured,
    TokenVerifierNotConfigured,
    ToolServerHostNotConfigured,
)
from .ports.event_sink import EventSink
from .ports.rate_limiter import RateLimiter
from .ports.token_broker import TokenBroker
from .ports.token_verifier import TokenVerifier
from .ports.tool_server_host import ToolServerHost
from .settings import CommonSettings


def lookup[T](registry: Mapping[str, Callable[..., T]], name: str, err: type[NotConfigured]) -> Any:
    """Tra registry adapter theo tên; tên lạ thì raise `err` kèm danh sách tên hợp lệ."""
    try:
        return registry[name]
    except KeyError:
        raise err(f"unknown adapter {name!r}; known: {sorted(registry)}") from None


def build_http_client(settings: CommonSettings) -> RetryingHttpClient:
    return RetryingHttpClient(
        timeout_s=settings.http_timeout_s, max_attempts=settings.http_max_attempts
    )


# --- Clock ---
def _load_system_clock(settings: CommonSettings) -> Clock:
    from .adapters.system_clock import SystemClock

    return SystemClock()


def _load_fake_clock(settings: CommonSettings) -> Clock:
    from .testing import FakeClock

    return FakeClock()


_CLOCKS: dict[str, Callable[[CommonSettings], Clock]] = {
    "system": _load_system_clock,
    "fake": _load_fake_clock,
}


def build_clock(name: str, settings: CommonSettings) -> Clock:
    return lookup(_CLOCKS, name, ClockNotConfigured)(settings)


# --- TokenVerifier ---
def _load_oidc_jwks(
    settings: CommonSettings, clock: Clock, http: RetryingHttpClient
) -> TokenVerifier:
    from .adapters.oidc_jwks import OidcJwksTokenVerifier

    return OidcJwksTokenVerifier(
        issuer=settings.keycloak_issuer,
        jwks_url=settings.jwks_url,
        http=http,
        clock=clock,
        algorithms=settings.algorithms,
        allowed_azp=settings.allowed_azp,
        required_scopes=settings.required_scopes,
        required_claims=settings.required_claims,
        leeway_s=settings.token_leeway_s,
        jwks_ttl_s=settings.jwks_cache_ttl_s,
        min_refetch_s=settings.jwks_min_refetch_s,
    )


_VERIFIERS: dict[str, Callable[[CommonSettings, Clock, RetryingHttpClient], TokenVerifier]] = {
    "oidc_jwks": _load_oidc_jwks,
}


def build_token_verifier(
    name: str,
    settings: CommonSettings,
    *,
    clock: Clock,
    http: RetryingHttpClient | None = None,
) -> TokenVerifier:
    loader = lookup(_VERIFIERS, name, TokenVerifierNotConfigured)
    return loader(settings, clock, http or build_http_client(settings))


# --- TokenBroker (bọc sẵn CachingTokenBroker) ---
def _load_oauth_token_exchange(
    settings: CommonSettings, clock: Clock, http: RetryingHttpClient, client_id: str, secret: str
) -> TokenBroker:
    from .adapters.oauth_token_exchange import OAuthTokenExchangeBroker

    return OAuthTokenExchangeBroker(
        token_url=settings.token_url,
        client_id=client_id,
        client_secret=secret,
        http=http,
        ignored_scopes=settings.ignored_scopes,
    )


def _load_static_broker(
    settings: CommonSettings, clock: Clock, http: RetryingHttpClient, client_id: str, secret: str
) -> TokenBroker:
    from .testing import FakeTokenBroker

    return FakeTokenBroker(clock)


_BROKERS: dict[
    str, Callable[[CommonSettings, Clock, RetryingHttpClient, str, str], TokenBroker]
] = {
    "oauth_token_exchange": _load_oauth_token_exchange,
    "static": _load_static_broker,
}


def build_token_broker(
    name: str,
    settings: CommonSettings,
    *,
    clock: Clock,
    client_id: str = "",
    client_secret: str = "",
    http: RetryingHttpClient | None = None,
    cache: bool = True,
) -> TokenBroker:
    """`client_id`/`client_secret` là của service gọi (vd `AGENT_KC_CLIENT_ID`), nên do caller truyền."""
    loader = lookup(_BROKERS, name, TokenBrokerNotConfigured)
    broker = loader(settings, clock, http or build_http_client(settings), client_id, client_secret)
    if cache:
        broker = CachingTokenBroker(broker, clock, skew_s=settings.token_cache_skew_s)
    return broker


# --- EventSink ---
def _load_json_log_sink(settings: CommonSettings) -> EventSink:
    from .adapters.json_log_event_sink import JsonLogEventSink

    return JsonLogEventSink()


def _load_postgres_sink(settings: CommonSettings) -> EventSink:
    from .adapters.postgres_event_sink import PostgresEventSink
    from .services.audit_chain import AuditKeyring

    dsn = settings.event_sink_database_url or settings.mcp_audit_database_url
    if not dsn:
        raise EventSinkNotConfigured(
            "postgres sink needs EVENT_SINK_DATABASE_URL or MCP_AUDIT_DATABASE_URL"
        )
    keyring = (
        AuditKeyring.single(settings.audit_hmac_key, settings.audit_hmac_key_id)
        if settings.audit_hmac_key
        else None
    )
    return PostgresEventSink(dsn, keyring)


_SINKS: dict[str, Callable[[CommonSettings], EventSink]] = {
    "json_log": _load_json_log_sink,
    "postgres": _load_postgres_sink,
}


def build_event_sink(name: str, settings: CommonSettings) -> EventSink:
    return lookup(_SINKS, name, EventSinkNotConfigured)(settings)


# --- RateLimiter ---
def _load_in_memory_limiter(settings: CommonSettings, clock: Clock) -> RateLimiter:
    from .adapters.in_memory_rate_limiter import InMemoryRateLimiter

    return InMemoryRateLimiter(clock)


_LIMITERS: dict[str, Callable[[CommonSettings, Clock], RateLimiter]] = {
    "in_memory": _load_in_memory_limiter,
}


def build_rate_limiter(name: str, settings: CommonSettings, *, clock: Clock) -> RateLimiter:
    return lookup(_LIMITERS, name, RateLimiterNotConfigured)(settings, clock)


# --- ToolServerHost ---
def _load_mcp_sdk_host(settings: CommonSettings, name: str) -> ToolServerHost:
    from .adapters.mcp_sdk import McpSdkHost

    return McpSdkHost(
        name,
        allowed_hosts=settings.mcp_allowed_hosts_set,
        allowed_origins=tuple(settings.mcp_allowed_origins_set),
    )


def _load_fake_host(settings: CommonSettings, name: str) -> ToolServerHost:
    from .testing import FakeToolServerHost

    return FakeToolServerHost()


_TOOL_HOSTS: dict[str, Callable[[CommonSettings, str], ToolServerHost]] = {
    "mcp_sdk": _load_mcp_sdk_host,
    "fake": _load_fake_host,
}


def build_tool_server_host(
    name: str, settings: CommonSettings, *, server_name: str
) -> ToolServerHost:
    """`name` thường là `settings.mcp_host`; `server_name` vd `docs-mcp`."""
    return lookup(_TOOL_HOSTS, name, ToolServerHostNotConfigured)(settings, server_name)
