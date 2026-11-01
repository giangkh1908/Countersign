"""Factory của agent: chọn adapter theo Settings (contracts §9.1 mục 5).

Registry dict + lazy import (import adapter bên trong loader), KHÔNG chuỗi if/elif.
Tên lạ -> raise XxxNotConfigured kèm danh sách tên hợp lệ. Ports: ToolProvider, ConversationRepository.
`PostgresSaver` và client OpenAI-compatible không bọc (hạ tầng cố định / chuẩn mở).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from acme_common.factory import lookup
from acme_common.ports import TokenBroker

from .agents import AgentRegistry, AgentSpec
from .ports.conversations import ConversationRepository
from .ports.errors import (
    AgentNotConfigured,
    CheckpointerNotConfigured,
    ConversationRepoNotConfigured,
    ServiceProbeNotConfigured,
    ToolProviderNotConfigured,
)
from .ports.service_probe import ServiceProbe
from .ports.tool_provider import ToolProvider
from .settings import Settings


# --- Agents ---
def _load_docs(settings: Settings) -> AgentSpec:
    from .agents.docs import load_docs_spec

    return load_docs_spec(settings)


def _load_ticket(settings: Settings) -> AgentSpec:
    from .agents.ticket import load_ticket_spec

    return load_ticket_spec(settings)


_AGENTS: dict[str, Callable[[Settings], AgentSpec]] = {"docs": _load_docs, "ticket": _load_ticket}


def build_agent_registry(settings: Settings, names: tuple[str, ...] | None = None) -> AgentRegistry:
    return AgentRegistry(
        lookup(_AGENTS, n, AgentNotConfigured)(settings) for n in (names or settings.enabled_agents)
    )


# --- ServiceProbe ---
def _load_http_probe(settings: Settings) -> ServiceProbe:
    from .adapters.http_probe import HttpServiceProbe

    return HttpServiceProbe()


_PROBES: dict[str, Callable[[Settings], ServiceProbe]] = {"http": _load_http_probe}


def build_service_probe(name: str, settings: Settings) -> ServiceProbe:
    return lookup(_PROBES, name, ServiceProbeNotConfigured)(settings)


# --- ToolProvider ---
def _load_mcp_http(
    settings: Settings, registry: AgentRegistry, broker: TokenBroker, write_broker: TokenBroker
) -> ToolProvider:
    from .adapters.mcp_http import McpHttpToolProvider

    return McpHttpToolProvider(
        settings.mcp_servers, broker, registry.access_map(), write_broker=write_broker
    )


_TOOL_PROVIDERS: dict[str, Callable[..., ToolProvider]] = {"mcp_http": _load_mcp_http}


def build_tool_provider(
    name: str,
    settings: Settings,
    *,
    registry: AgentRegistry,
    broker: TokenBroker,
    write_broker: TokenBroker,
) -> ToolProvider:
    return lookup(_TOOL_PROVIDERS, name, ToolProviderNotConfigured)(
        settings, registry, broker, write_broker
    )


# --- ConversationRepository ---
async def _load_memory_repo(
    settings: Settings,
) -> tuple[ConversationRepository, Callable[[], Awaitable[None]]]:
    from .adapters.memory_conversations import MemoryConversationRepository

    async def close() -> None: ...

    return MemoryConversationRepository(), close


async def _load_postgres_repo(
    settings: Settings,
) -> tuple[ConversationRepository, Callable[[], Awaitable[None]]]:
    from psycopg_pool import AsyncConnectionPool

    from .adapters.postgres_conversations import PostgresConversationRepository

    if not settings.agent_database_url:
        raise CheckpointerNotConfigured("AGENT_DATABASE_URL is required for postgres adapters")
    pool = AsyncConnectionPool(
        settings.agent_database_url, kwargs={"autocommit": True, "prepare_threshold": 0}, open=False
    )
    await pool.open()
    return PostgresConversationRepository(pool), pool.close


_REPOS: dict[
    str,
    Callable[[Settings], Awaitable[tuple[ConversationRepository, Callable[[], Awaitable[None]]]]],
] = {
    "memory": _load_memory_repo,
    "postgres": _load_postgres_repo,
}


async def build_conversation_repo(
    name: str, settings: Settings
) -> tuple[ConversationRepository, Callable[[], Awaitable[None]]]:
    return await lookup(_REPOS, name, ConversationRepoNotConfigured)(settings)


# --- Checkpointer (mã hoá serializer, ADR-004) ---
def build_serde(settings: Settings) -> Any:
    """`EncryptedSerializer` (AES-EAX) khi có khoá; ngoài `ACME_ENV=test` thiếu khoá => ConfigError."""
    from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    key = settings.checkpoint_key_bytes()
    if key is None:
        return JsonPlusSerializer()
    return EncryptedSerializer.from_pycryptodome_aes(key=key)


async def _load_memory_saver(settings: Settings) -> tuple[Any, Callable[[], Awaitable[None]]]:
    from langgraph.checkpoint.memory import InMemorySaver

    async def close() -> None: ...

    return InMemorySaver(serde=build_serde(settings)), close


async def _load_postgres_saver(settings: Settings) -> tuple[Any, Callable[[], Awaitable[None]]]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    serde = build_serde(settings)  # kiểm khoá trước khi mở kết nối
    if not settings.agent_database_url:
        raise CheckpointerNotConfigured("AGENT_DATABASE_URL is required for postgres adapters")
    pool = AsyncConnectionPool(
        settings.agent_database_url,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    # setup() (DDL) chạy trong job migration bằng ag_owner, KHÔNG chạy lúc runtime.
    return AsyncPostgresSaver(pool, serde=serde), pool.close


_CHECKPOINTERS: dict[
    str, Callable[[Settings], Awaitable[tuple[Any, Callable[[], Awaitable[None]]]]]
] = {
    "memory": _load_memory_saver,
    "postgres": _load_postgres_saver,
}


async def build_checkpointer(
    name: str, settings: Settings
) -> tuple[Any, Callable[[], Awaitable[None]]]:
    return await lookup(_CHECKPOINTERS, name, CheckpointerNotConfigured)(settings)


__all__ = [
    "build_agent_registry",
    "build_service_probe",
    "build_checkpointer",
    "build_conversation_repo",
    "build_serde",
    "build_tool_provider",
]
