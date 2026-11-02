"""Factory của mcp_notify: chọn adapter theo Settings (contracts §9.1 mục 5).

Quy tắc: registry dict + lazy import (import adapter bên trong loader), KHÔNG dùng chuỗi if/elif.
Tên lạ -> raise XxxNotConfigured kèm danh sách tên hợp lệ.

Không có adapter `permissive` cho IntentIssuer/ApprovalVerifier. Adapter `fake` của MessageChannel chọn
được bằng `adapter: fake` trong file kênh (test, eval, demo không token), không phải đường tắt qua xác thực.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any

from acme_common.factory import lookup
from acme_common.ports import Clock

from .channels import ChannelConfig, env_chat_resolver
from .ports import (
    ApprovalVerifier,
    ApprovalVerifierNotConfigured,
    DeliveryLog,
    DeliveryLogNotConfigured,
    IntentIssuer,
    IntentIssuerNotConfigured,
    MessageChannel,
    MessageChannelNotConfigured,
    ReplayGuard,
    ReplayGuardNotConfigured,
)
from .retrying import RetryingMessageChannel
from .settings import Settings


def _redis_ns(s: Settings) -> str:
    """`mcp:<tên>:` theo ACL Redis (mỗi MCP một user, một tiền tố): `notify-mcp` -> `mcp:notify:`."""
    return f"mcp:{s.mcp_audience.removesuffix('-mcp')}:"


# --- MessageChannel (bọc sẵn RetryingMessageChannel) ---
def _load_telegram(s: Settings) -> MessageChannel:
    from .adapters.telegram import TelegramMessageChannel

    if not s.telegram_bot_token:
        raise MessageChannelNotConfigured("telegram needs TELEGRAM_BOT_TOKEN(_FILE)")
    return TelegramMessageChannel(
        s.telegram_bot_token, env_chat_resolver, api_base=s.telegram_api_base
    )


def _load_fake(s: Settings) -> MessageChannel:
    from .adapters.fake import FakeMessageChannel

    return FakeMessageChannel()


_CHANNEL_ADAPTERS: dict[str, Callable[[Settings], MessageChannel]] = {
    "telegram": _load_telegram,
    "fake": _load_fake,
}


def build_message_channel(name: str, settings: Settings) -> MessageChannel:
    inner = lookup(_CHANNEL_ADAPTERS, name, MessageChannelNotConfigured)(settings)
    return RetryingMessageChannel(
        inner,
        max_attempts=settings.message_retry_attempts,
        max_wait_s=settings.message_retry_max_wait_s,
    )


def build_senders(
    channels: Mapping[str, ChannelConfig], settings: Settings
) -> dict[str, MessageChannel]:
    """Mỗi adapter được khai trong file kênh dựng đúng một instance."""
    names: Collection[str] = sorted({c.adapter for c in channels.values()})
    return {n: build_message_channel(n, settings) for n in names}


# --- DeliveryLog ---
def _load_postgres_deliveries(s: Settings) -> DeliveryLog:
    from .adapters.postgres_deliveries import PostgresDeliveryLog

    if not s.mcp_database_url:
        raise DeliveryLogNotConfigured("postgres delivery log needs MCP_DATABASE_URL")
    return PostgresDeliveryLog(s.mcp_database_url)


_DELIVERY_LOGS: dict[str, Callable[[Settings], DeliveryLog]] = {
    "postgres": _load_postgres_deliveries,
}


def build_delivery_log(name: str, settings: Settings) -> DeliveryLog:
    return lookup(_DELIVERY_LOGS, name, DeliveryLogNotConfigured)(settings)


# --- IntentIssuer ---
def _load_es256_jws(s: Settings, redis: Any, clock: Clock) -> IntentIssuer:
    from acme_common.adapters.intent_es256_jws import Es256JwsIntentIssuer

    if not s.intent_private_key_path:
        raise IntentIssuerNotConfigured("es256_jws needs INTENT_PRIVATE_KEY_PATH")
    return Es256JwsIntentIssuer(
        redis,
        private_key_pem=Path(s.intent_private_key_path).read_bytes(),
        key_id=s.intent_key_id,
        clock=clock,
        issuer=s.mcp_audience,
        redis_prefix=_redis_ns(s) + "intent:",
        ttl_s=s.intent_ttl_s,
        audience=s.intent_audience,
    )


_ISSUERS: dict[str, Callable[[Settings, Any, Clock], IntentIssuer]] = {
    "es256_jws": _load_es256_jws,
}


def build_intent_issuer(name: str, settings: Settings, *, redis: Any, clock: Clock) -> IntentIssuer:
    return lookup(_ISSUERS, name, IntentIssuerNotConfigured)(settings, redis, clock)


# --- ApprovalVerifier ---
def _load_es256_jwt(s: Settings, clock: Clock) -> ApprovalVerifier:
    from acme_common.adapters.approval_es256_jwt import Es256JwtApprovalVerifier, load_trusted_keys

    if not s.approval_public_key_path:
        raise ApprovalVerifierNotConfigured("es256_jwt needs APPROVAL_PUBLIC_KEY_PATH")
    return Es256JwtApprovalVerifier(
        load_trusted_keys(s.approval_public_key_path, s.approval_key_id),
        clock,
        audience=s.mcp_audience,
        max_ttl_s=s.approval_max_ttl_s,
    )


_VERIFIERS: dict[str, Callable[[Settings, Clock], ApprovalVerifier]] = {
    "es256_jwt": _load_es256_jwt,
}


def build_approval_verifier(name: str, settings: Settings, *, clock: Clock) -> ApprovalVerifier:
    return lookup(_VERIFIERS, name, ApprovalVerifierNotConfigured)(settings, clock)


# --- ReplayGuard ---
def _load_redis_replay(s: Settings, redis: Any, clock: Clock) -> ReplayGuard:
    from acme_common.adapters.replay_redis import RedisReplayGuard

    return RedisReplayGuard(redis, prefix=_redis_ns(s) + "jti:")


def _load_in_memory_replay(s: Settings, redis: Any, clock: Clock) -> ReplayGuard:
    from acme_common.adapters.replay_memory import InMemoryReplayGuard

    return InMemoryReplayGuard(clock)


_REPLAY_GUARDS: dict[str, Callable[[Settings, Any, Clock], ReplayGuard]] = {
    "redis": _load_redis_replay,
    "in_memory": _load_in_memory_replay,
}


def build_replay_guard(name: str, settings: Settings, *, redis: Any, clock: Clock) -> ReplayGuard:
    return lookup(_REPLAY_GUARDS, name, ReplayGuardNotConfigured)(settings, redis, clock)
