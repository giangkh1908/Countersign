"""Factory của mcp_tickets: chọn adapter theo Settings (contracts §9.1 mục 5).

Quy tắc: registry dict + lazy import (import adapter bên trong loader), KHÔNG dùng chuỗi if/elif.
Tên lạ -> raise XxxNotConfigured kèm danh sách tên hợp lệ. ToolServerHost lấy từ
`acme_common.factory.build_tool_server_host`.

Không có adapter `permissive` cho IntentIssuer/ApprovalVerifier: chỉ thêm khi cần ablation
(ACME_ENV=eval, §9.1 mục 11).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from acme_common.ports import Clock
from acme_common.ports.errors import NotConfigured
from acme_common.services.audit_chain import AuditKeyring

from .ports import (
    ApprovalVerifier,
    ApprovalVerifierNotConfigured,
    IntentIssuer,
    IntentIssuerNotConfigured,
    ReplayGuard,
    ReplayGuardNotConfigured,
    TicketRepository,
    TicketRepositoryNotConfigured,
)
from .settings import Settings


def _lookup(registry: Mapping[str, Callable[..., Any]], name: str, err: type[NotConfigured]) -> Any:
    try:
        return registry[name]
    except KeyError:
        raise err(f"unknown adapter {name!r}; known: {sorted(registry)}") from None


# --- TicketRepository ---
def _load_postgres_repository(s: Settings) -> TicketRepository:
    from .adapters.postgres_tickets import PostgresTicketRepository

    if not s.mcp_database_url:
        raise TicketRepositoryNotConfigured("postgres repository needs MCP_DATABASE_URL")
    if not s.audit_hmac_key:
        raise TicketRepositoryNotConfigured("postgres repository needs AUDIT_HMAC_KEY")
    keyring = AuditKeyring.single(s.audit_hmac_key, s.audit_hmac_key_id)
    return PostgresTicketRepository(s.mcp_database_url, keyring, audit_actor=s.mcp_audience)


_REPOSITORIES: dict[str, Callable[[Settings], TicketRepository]] = {
    "postgres": _load_postgres_repository,
}


def build_ticket_repository(name: str, settings: Settings) -> TicketRepository:
    return _lookup(_REPOSITORIES, name, TicketRepositoryNotConfigured)(settings)


# --- IntentIssuer ---
def _load_es256_jws(s: Settings, redis: Any, clock: Clock) -> IntentIssuer:
    from .adapters.es256_jws import Es256JwsIntentIssuer

    if not s.intent_private_key_path:
        raise IntentIssuerNotConfigured("es256_jws needs INTENT_PRIVATE_KEY_PATH")
    return Es256JwsIntentIssuer(
        redis,
        private_key_pem=Path(s.intent_private_key_path).read_bytes(),
        key_id=s.intent_key_id,
        clock=clock,
        ttl_s=s.intent_ttl_s,
        audience=s.intent_audience,
    )


_ISSUERS: dict[str, Callable[[Settings, Any, Clock], IntentIssuer]] = {
    "es256_jws": _load_es256_jws,
}


def build_intent_issuer(name: str, settings: Settings, *, redis: Any, clock: Clock) -> IntentIssuer:
    return _lookup(_ISSUERS, name, IntentIssuerNotConfigured)(settings, redis, clock)


# --- ApprovalVerifier ---
def _load_es256_jwt(s: Settings, clock: Clock) -> ApprovalVerifier:
    from .adapters.es256_jwt import Es256JwtApprovalVerifier, load_trusted_keys

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
    return _lookup(_VERIFIERS, name, ApprovalVerifierNotConfigured)(settings, clock)


# --- ReplayGuard ---
def _load_redis_replay(s: Settings, redis: Any, clock: Clock) -> ReplayGuard:
    from .adapters.redis_replay import RedisReplayGuard

    return RedisReplayGuard(redis)


def _load_in_memory_replay(s: Settings, redis: Any, clock: Clock) -> ReplayGuard:
    from .adapters.in_memory_replay import InMemoryReplayGuard

    return InMemoryReplayGuard(clock)


_REPLAY_GUARDS: dict[str, Callable[[Settings, Any, Clock], ReplayGuard]] = {
    "redis": _load_redis_replay,
    "in_memory": _load_in_memory_replay,
}


def build_replay_guard(name: str, settings: Settings, *, redis: Any, clock: Clock) -> ReplayGuard:
    return _lookup(_REPLAY_GUARDS, name, ReplayGuardNotConfigured)(settings, redis, clock)
