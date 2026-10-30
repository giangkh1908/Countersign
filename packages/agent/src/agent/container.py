"""Container phụ thuộc của agent: dựng từ Settings qua factory; test dựng tay bằng fake."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from acme_common.factory import (
    build_clock,
    build_http_client,
    build_token_broker,
    build_token_verifier,
)
from acme_common.ports import Clock, TokenBroker, TokenVerifier
from langchain_core.language_models.chat_models import BaseChatModel

from .agents import AgentRegistry
from .availability import resolve_enabled_agents
from .factory import (
    build_agent_registry,
    build_checkpointer,
    build_conversation_repo,
    build_service_probe,
    build_tool_provider,
)
from .graph.builder import build_graph
from .ports.conversations import ConversationRepository
from .ports.service_probe import ServiceProbe
from .ports.tool_provider import ToolProvider
from .settings import Settings

# (gateway_user_token, run_id) -> (role -> chat model)
ChatFactory = Callable[[str, str], Callable[[str], BaseChatModel]]


@dataclass
class Container:
    settings: Settings
    verifier: TokenVerifier
    broker: TokenBroker
    tool_provider: ToolProvider
    registry: AgentRegistry
    graph: Any
    checkpointer: Any
    repo: ConversationRepository
    clock: Clock
    chat_factory: ChatFactory
    write_broker: TokenBroker | None = None
    base_settings: Settings | None = None  # trước khi lọc agent tuỳ chọn (availability)
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)


async def build_container(settings: Settings) -> Container:
    from .llm import build_llm_http_client, make_chat_model

    clock = build_clock(settings.clock_adapter, settings)
    http = build_http_client(settings)
    verifier = build_token_verifier(
        settings.token_verifier_adapter, settings, clock=clock, http=http
    )
    kw = {
        "clock": clock,
        "client_id": settings.agent_kc_client_id,
        "client_secret": settings.agent_kc_client_secret or "",
        "http": http,
    }
    broker = build_token_broker(settings.token_broker_adapter, settings, **kw)
    write_broker = build_token_broker(settings.token_broker_adapter, settings, cache=False, **kw)
    base_settings = settings
    settings = await resolve_enabled_agents(
        settings, build_service_probe(settings.service_probe_adapter, settings)
    )
    registry = build_agent_registry(settings)
    provider = build_tool_provider(
        settings.tool_provider_adapter,
        settings,
        registry=registry,
        broker=broker,
        write_broker=write_broker,
    )
    saver, close_saver = await build_checkpointer(settings.checkpointer_adapter, settings)
    repo, close_repo = await build_conversation_repo(settings.conversation_repo_adapter, settings)
    llm_http = build_llm_http_client()

    def chat_factory(gw_token: str, run_id: str) -> Callable[[str], BaseChatModel]:
        return lambda role: make_chat_model(
            role,
            settings=settings,
            gateway_user_token=gw_token,
            run_id=run_id,
            http_client=llm_http,
        )

    return Container(
        settings=settings,
        verifier=verifier,
        broker=broker,
        tool_provider=provider,
        registry=registry,
        graph=build_graph(saver, registry),
        checkpointer=saver,
        repo=repo,
        clock=clock,
        chat_factory=chat_factory,
        write_broker=write_broker,
        base_settings=base_settings,
        closers=[close_saver, close_repo, llm_http.aclose],
    )


async def refresh_optional_agents(c: Container, probe: ServiceProbe) -> bool:
    """Dò lại agent tuỳ chọn (vd. bật profile `tickets` sau khi agent đã chạy). True nếu đổi tập agent.

    Dựng lại registry/provider/graph trên cùng checkpointer; các endpoint đọc container theo từng request.
    """
    if c.base_settings is None or c.write_broker is None:
        return False
    if c.settings.enabled_agents == c.base_settings.enabled_agents:
        return False  # không có agent tuỳ chọn nào đang tắt: khỏi dò
    settings = await resolve_enabled_agents(c.base_settings, probe)
    if settings.enabled_agents == c.settings.enabled_agents:
        return False
    registry = build_agent_registry(settings)
    c.tool_provider = build_tool_provider(
        settings.tool_provider_adapter,
        settings,
        registry=registry,
        broker=c.broker,
        write_broker=c.write_broker,
    )
    c.graph = build_graph(c.checkpointer, registry)
    c.registry = registry
    c.settings = settings
    return True
