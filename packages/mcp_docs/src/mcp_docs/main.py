"""Điểm vào ASGI của mcp_docs: `uvicorn mcp_docs.main:app` (dựng lười ở request/lifespan đầu tiên).

`build_runtime()` ghép composition root: settings -> factory -> service -> ToolInvoker -> host ->
AuthMiddleware, cộng endpoint `/internal/taint/forget`. Test truyền fake qua tham số.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acme_common.factory import (
    build_clock,
    build_event_sink,
    build_rate_limiter,
    build_token_verifier,
    build_tool_server_host,
)
from acme_common.mcp import AuthMiddleware, ToolInvoker
from acme_common.ports import (
    Clock,
    EventSink,
    RateLimiter,
    TokenVerifier,
    ToolServerHost,
)

from .api.forget import PATH as FORGET_PATH
from .api.forget import TaintForgetEndpoint
from .api.tools import search_handler, search_spec
from .factory import build_embedder, build_reranker, build_retriever
from .ports import DocumentRetriever, Reranker
from .services.document_service import DocumentService
from .settings import Settings

SERVER = "docs-mcp"


@dataclass
class Runtime:
    settings: Settings
    host: ToolServerHost
    invoker: ToolInvoker
    service: DocumentService
    app: Any  # ASGI


class _Router:
    """ASGI: `/internal/taint/forget` -> endpoint riêng; còn lại -> AuthMiddleware(host)."""

    def __init__(self, mcp_app: Any, forget: TaintForgetEndpoint) -> None:
        self._mcp = mcp_app
        self._forget = forget

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] == FORGET_PATH:
            await self._forget(scope, receive, send)
        else:
            await self._mcp(scope, receive, send)


def _sink_name(s: Settings) -> str:
    return s.docs_audit_sink or ("postgres" if s.mcp_audit_database_url else s.event_sink_adapter)


def build_runtime(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    verifier: TokenVerifier | None = None,
    forget_verifier: TokenVerifier | None = None,
    retriever: DocumentRetriever | None = None,
    reranker: Reranker | None = None,
    redis: Any | None = None,
    audit: EventSink | None = None,
    limiter: RateLimiter | None = None,
) -> Runtime:
    s = settings or Settings()
    clock = clock or build_clock("system", s)
    if redis is None and s.mcp_redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(s.mcp_redis_url)
    if retriever is None:
        embedder = build_embedder(s.docs_embedder, s)
        retriever = build_retriever(s.docs_retriever, s, embedder=embedder)
    reranker = reranker or build_reranker(s.docs_rerank, s)
    verifier = verifier or build_token_verifier("oidc_jwks", s, clock=clock)
    # token của job retention không mang dept/clearance => verifier riêng chỉ đòi `sub`
    forget_verifier = forget_verifier or build_token_verifier(
        "oidc_jwks", s.model_copy(update={"token_required_claims": "sub"}), clock=clock
    )
    audit = audit or build_event_sink(_sink_name(s), s)
    limiter = limiter or build_rate_limiter("in_memory", s, clock=clock)

    service = DocumentService(
        retriever,
        reranker,
        redis=redis,
        recent_ttl_s=s.taint_recent_ttl_s,
        retention_s=s.agent_thread_retention_days * 86400,
        max_per_doc=s.docs_max_per_doc,
    )
    invoker = ToolInvoker(
        server=SERVER,
        limiter=limiter,
        audit=audit,
        clock=clock,
        rl_capacity=s.mcp_rl_capacity,
        rl_refill_per_s=s.mcp_rl_refill_per_s,
    )
    host = build_tool_server_host(s.mcp_host, s, server_name=SERVER)
    spec = search_spec(max_output_bytes=s.mcp_max_output_bytes)
    host.register(spec, invoker.wrap(spec, search_handler(service)))

    scopes = {spec.name: spec.required_scopes}
    mcp_app = AuthMiddleware(
        host.asgi_app(),
        verifier=verifier,
        audience=s.mcp_audience,
        resource_url=s.mcp_public_url or None,
        scopes_supported=("docs:read",),
        allowed_azp=s.mcp_allowed_azp_set,
        allowed_origins=s.mcp_allowed_origins_set,
        required_scopes_for=lambda name: scopes.get(name),
    )
    forget = TaintForgetEndpoint(
        verifier=forget_verifier,
        audience=s.mcp_audience,
        redis=redis,
        audit=audit,
        clock=clock,
        allowed_azp=frozenset(x for x in s.forget_allowed_azp.replace(" ", ",").split(",") if x),
    )
    return Runtime(s, host, invoker, service, _Router(mcp_app, forget))


class _LazyApp:
    """Dựng runtime ở lần gọi đầu (import module không đòi env/DB)."""

    def __init__(self) -> None:
        self._app: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._app is None:
            self._app = build_runtime().app
        await self._app(scope, receive, send)


app = _LazyApp()
