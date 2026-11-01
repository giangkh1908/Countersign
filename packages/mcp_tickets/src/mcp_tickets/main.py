"""Điểm vào ASGI của tickets-mcp: `uvicorn mcp_tickets.main:app --port 8102`.

`app` dựng mọi thành phần ở lifespan startup (import không cần env/DB). `build_app()` dùng cho test.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from acme_common.factory import (
    build_clock,
    build_event_sink,
    build_rate_limiter,
    build_token_verifier,
    build_tool_server_host,
)
from acme_common.mcp import AuthMiddleware, ToolInvoker
from acme_common.ports import Clock, ToolServerHost

from .factory import (
    build_approval_verifier,
    build_intent_issuer,
    build_replay_guard,
    build_ticket_repository,
)
from .services.ticket_service import TicketService
from .settings import Settings
from .tools import register_tools, required_scopes_for

log = logging.getLogger("acme.mcp_tickets")

SERVER = "tickets-mcp"


class Runtime:
    """Các thành phần đã nối dây; `asgi` là app đã bọc `AuthMiddleware`."""

    def __init__(self, host: ToolServerHost, asgi: Any, service: TicketService, redis: Any) -> None:
        self.host, self.asgi, self.service, self.redis = host, asgi, service, redis

    @contextlib.asynccontextmanager
    async def lifespan(self) -> Any:
        inner = self.host.asgi_app()
        lifespan_ctx = getattr(getattr(inner, "router", None), "lifespan_context", None)
        async with contextlib.AsyncExitStack() as stack:
            if lifespan_ctx is not None:  # session manager của MCP SDK
                await stack.enter_async_context(lifespan_ctx(inner))
            try:
                yield
            finally:
                with contextlib.suppress(Exception):
                    await self.redis.aclose()


def build_runtime(settings: Settings | None = None, *, clock: Clock | None = None) -> Runtime:
    import redis.asyncio as aioredis

    s = settings or Settings()
    clock = clock or build_clock(s.clock_adapter, s)
    if not s.mcp_redis_url:
        raise ValueError("MCP_REDIS_URL is required")
    redis = aioredis.Redis.from_url(s.mcp_redis_url, decode_responses=True)

    verifier = build_token_verifier(s.token_verifier_adapter, s, clock=clock)
    invoker = ToolInvoker(
        server=SERVER,
        limiter=build_rate_limiter(s.rate_limiter_adapter, s, clock=clock),
        audit=build_event_sink("postgres", s),
        clock=clock,
        rl_capacity=s.mcp_rl_capacity,
        rl_refill_per_s=s.mcp_rl_refill_per_s,
    )
    service = TicketService(
        build_ticket_repository(s.tickets_repository, s),
        build_intent_issuer(s.intent_issuer, s, redis=redis, clock=clock),
        build_approval_verifier(s.approval_verifier, s, clock=clock),
        build_replay_guard(s.replay_guard, s, redis=redis, clock=clock),
        clock,
        redis,
        taint_policy=s.taint_policy,
        taint_recent_ttl_s=s.taint_recent_ttl_s,
        replay_ttl_s=s.replay_ttl_s,
    )
    host = build_tool_server_host(s.mcp_host, s, server_name=SERVER)
    register_tools(host, invoker, service)
    asgi = AuthMiddleware(
        host.asgi_app(),
        verifier=verifier,
        audience=s.mcp_audience,
        resource_url=s.mcp_public_url or None,
        allowed_azp=s.mcp_allowed_azp_set,
        allowed_origins=s.mcp_allowed_origins_set,
        required_scopes_for=required_scopes_for,
    )
    return Runtime(host, asgi, service, redis)


class TicketsMcpApp:
    """ASGI app: lifespan dựng `Runtime` (lỗi cấu hình => dừng khởi động), http chuyển cho `AuthMiddleware`."""

    def __init__(self, factory: Callable[[], Runtime] = build_runtime) -> None:
        self._factory = factory
        self._rt: Runtime | None = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if self._rt is None:
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await self._rt.asgi(scope, receive, send)

    async def _lifespan(self, receive: Any, send: Any) -> None:
        msg = await receive()
        assert msg["type"] == "lifespan.startup"
        try:
            rt = self._factory()
            ctx = rt.lifespan()
            await ctx.__aenter__()
        except Exception as e:  # noqa: BLE001 - báo cho server, không lộ chi tiết
            log.exception("startup failed")
            await send({"type": "lifespan.startup.failed", "message": type(e).__name__})
            return
        self._rt = rt
        await send({"type": "lifespan.startup.complete"})
        await receive()  # lifespan.shutdown
        with contextlib.suppress(Exception):
            await ctx.__aexit__(None, None, None)
        await send({"type": "lifespan.shutdown.complete"})


app = TicketsMcpApp()
