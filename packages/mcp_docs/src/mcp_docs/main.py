"""Điểm vào ASGI của mcp_docs: `uvicorn mcp_docs.main:app` (dựng lười ở request/lifespan đầu tiên).

`build_runtime()` ghép composition root: settings -> factory -> service -> ToolInvoker -> host ->
AuthMiddleware, cộng endpoint `/internal/taint/forget`. Test truyền fake qua tham số.
"""

from __future__ import annotations

import logging
import time
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
from acme_common.log import configure_logging
from acme_common.mcp import AuthMiddleware, CallerContext, ToolInvoker, ToolOutput
from acme_common.metrics import CONTENT_TYPE, bearer_ok, metrics_body
from acme_common.ports import (
    Clock,
    EventSink,
    RateLimiter,
    TokenVerifier,
    ToolServerHost,
)
from acme_common.telemetry import span, traced_asgi
from prometheus_client import CollectorRegistry, Counter, Histogram

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


class RetrievalMetrics:
    """Metric truy xuất của docs-mcp. Nhãn chỉ gồm `mode` và `outcome` (tập hữu hạn)."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.total = Counter(
            "docs_retrieval_total",
            "Lượt truy xuất theo chế độ và kết quả",
            ["mode", "outcome"],
            registry=registry,
        )
        self.duration = Histogram(
            "docs_retrieval_duration_seconds",
            "Thời gian truy xuất (hybrid, kèm rerank)",
            ["mode"],
            registry=registry,
        )
        self.returned = Histogram(
            "docs_retrieval_returned",
            "Số đoạn trả về mỗi lượt",
            buckets=(0, 1, 2, 3, 5, 8, 12, 20),
            registry=registry,
        )

    def wrap(self, handler: Any) -> Any:
        """Đo thời gian + mở span `retrieval` (chỉ số đếm, không nội dung)."""

        async def run(ctx: CallerContext, args: dict[str, Any]) -> Any:
            start = time.perf_counter()
            with span("retrieval") as sp:
                try:
                    out = await handler(ctx, args)
                except Exception:
                    self.total.labels("unknown", "error").inc()
                    raise
                data = out.data if isinstance(out, ToolOutput) else out
                mode = str(data.get("mode", "unknown"))
                n = len(data.get("results", ()))
                sp.set_attribute("mode", mode)
                sp.set_attribute("returned", n)
                sp.set_attribute("reranked", bool(data.get("reranked", False)))
            self.total.labels(mode, "ok").inc()
            self.duration.labels(mode).observe(time.perf_counter() - start)
            self.returned.observe(n)
            return out

        return run


@dataclass
class Runtime:
    settings: Settings
    host: ToolServerHost
    invoker: ToolInvoker
    service: DocumentService
    app: Any  # ASGI
    # kiểm cấu hình lúc khởi động (schema, số chiều, embedder); sai => IndexConfigError, dừng dịch vụ
    startup_check: Callable[[], Awaitable[None]] = field(default=_noop)
    registry: CollectorRegistry = field(default_factory=CollectorRegistry)


class _Router:
    """ASGI: `/internal/taint/forget`, `/metrics` -> endpoint riêng; còn lại -> AuthMiddleware(host)."""

    def __init__(
        self,
        mcp_app: Any,
        forget: TaintForgetEndpoint,
        registry: CollectorRegistry,
        metrics_token: str | None,
    ) -> None:
        self._mcp = mcp_app
        self._forget = forget
        self._registry = registry
        self._metrics_token = metrics_token

    async def _metrics(self, scope: Any, send: Any) -> None:
        auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        if bearer_ok(auth, self._metrics_token):
            status, body, ctype = 200, metrics_body(self._registry), CONTENT_TYPE
        else:
            status, body, ctype = 401, b"", "text/plain"
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", ctype.encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] == FORGET_PATH:
            await self._forget(scope, receive, send)
        elif scope["type"] == "http" and scope["path"] == "/metrics":
            await self._metrics(scope, send)
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
        rerank_top_n=s.docs_rerank_top_n,
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
    registry = CollectorRegistry()
    host.register(
        spec, invoker.wrap(spec, RetrievalMetrics(registry).wrap(search_handler(service)))
    )

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

    router = _Router(mcp_app, forget, registry, s.metrics_token)
    return Runtime(s, host, invoker, service, router, startup_check, registry)


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
                    configure_logging(Settings().log_level, SERVER)
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


app = traced_asgi(_LazyApp(), SERVER)
