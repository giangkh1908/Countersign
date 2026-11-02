"""Điểm vào ASGI của mcp_docs: `uvicorn mcp_docs.main:app` (dựng lười ở request/lifespan đầu tiên).

`build_runtime()` ghép composition root: settings -> factory -> service -> ToolInvoker -> host ->
AuthMiddleware, cộng endpoint `/internal/taint/forget`. Test truyền fake qua tham số.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
from .factory import build_article_reader, build_embedder, build_reranker, build_retriever
from .ports import (
    ArticleReader,
    DocumentRetriever,
    Embedder,
    EmbeddingUnavailable,
    IndexConfigError,
    Reranker,
    RetrievalUnavailable,
)
from .services.document_service import DocumentService
from .services.index_checks import probe_embedder
from .settings import Settings

SERVER = "docs-mcp"
log = logging.getLogger("acme.docs")


async def _noop() -> None:
    return None


@dataclass
class Runtime:
    settings: Settings
    host: ToolServerHost
    invoker: ToolInvoker
    service: DocumentService
    app: Any  # ASGI
    # kiểm cấu hình lúc khởi động (schema, số chiều, embedder); sai => IndexConfigError, dừng dịch vụ
    startup_check: Callable[[], Awaitable[None]] = field(default=_noop)


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
    article_reader: ArticleReader | None = None,
    redis: Any | None = None,
    audit: EventSink | None = None,
    limiter: RateLimiter | None = None,
) -> Runtime:
    s = settings or Settings()
    clock = clock or build_clock("system", s)
    if redis is None and s.mcp_redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(s.mcp_redis_url)
    embedder: Embedder | None = None
    if retriever is None:
        embedder = build_embedder(s.docs_embedder, s)
        retriever = build_retriever(s.docs_retriever, s, embedder=embedder)
    if article_reader is None and s.docs_direct_lookup != "off":
        article_reader = build_article_reader(s.docs_retriever, s)
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
        article_reader=article_reader,
        direct_lookup=s.docs_direct_lookup,
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
    checked_retriever, checked_embedder = retriever, embedder

    async def startup_check() -> None:
        model: str | None = None
        if checked_embedder is not None and s.docs_use_vector:
            await probe_embedder(checked_embedder, s.docs_embed_dim)
            model = checked_embedder.model_id  # id thật sau lần gọi thăm dò
        await checked_retriever.verify_schema(
            s.docs_embed_dim, embed_model=model, strict_meta=s.docs_strict_index_meta
        )

    return Runtime(s, host, invoker, service, _Router(mcp_app, forget), startup_check)


class _LazyApp:
    """Dựng runtime ở lần gọi đầu (import module không đòi env/DB).

    Ở scope `lifespan`, kiểm cấu hình trước khi báo startup xong: sai số chiều thì báo
    `lifespan.startup.failed` để uvicorn dừng với thông báo rõ, thay vì chạy sai.
    """

    def __init__(self) -> None:
        self._rt: Runtime | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            first = await receive()
            if first["type"] == "lifespan.startup":
                try:
                    rt = self._rt = self._rt or build_runtime()
                    await rt.startup_check()
                except IndexConfigError as e:
                    log.error("docs-mcp startup check failed: %s", e)
                    await send({"type": "lifespan.startup.failed", "message": str(e)})
                    return
                except (RetrievalUnavailable, EmbeddingUnavailable) as e:
                    # kho/gateway chưa sẵn sàng không phải cấu hình sai: truy vấn tự suy giảm
                    log.warning("docs-mcp startup check skipped: %s", e)
            replay = [first]

            async def replay_receive() -> Any:
                return replay.pop() if replay else await receive()

            await self._rt_app()(scope, replay_receive, send)
            return
        await self._rt_app()(scope, receive, send)

    def _rt_app(self) -> Any:
        if self._rt is None:
            self._rt = build_runtime()
        return self._rt.app


app = _LazyApp()
