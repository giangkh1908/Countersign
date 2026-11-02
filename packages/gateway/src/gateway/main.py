"""Entrypoint FastAPI của gateway: `uvicorn gateway.main:app`."""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from acme_common.log import configure_logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.chat import router as chat_router
from .api.embeddings import router as embeddings_router
from .api.middleware import RequestIdMiddleware
from .container import Container, build_container
from .services.errors import GatewayError
from .settings import Settings

log = logging.getLogger("gateway.main")


async def _flush_loop(c: Container, interval_s: float) -> None:
    """Đẩy buffer EventSink định kỳ; lỗi chỉ log, không làm chết vòng lặp."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            await c.sink.flush(interval_s)
        except Exception:  # noqa: BLE001 - sink hỏng không được ảnh hưởng request
            log.warning("event sink flush failed", exc_info=True)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """`container` tiêm sẵn (test) hoặc để None: lifespan dựng từ settings qua factory."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, "gateway")
        c = container or build_container(settings)
        app.state.container = c
        flusher = asyncio.create_task(_flush_loop(c, settings.gw_sink_flush_interval_s))
        try:
            yield
        finally:
            flusher.cancel()
            await asyncio.gather(flusher, return_exceptions=True)
            await c.sink.flush(5.0)
            for close in c.closers:
                await close()

    app = FastAPI(title="LLM Gateway", lifespan=lifespan)
    app.state.max_body_bytes = settings.gw_max_body_bytes
    if container is not None:  # test dùng ASGITransport không chạy lifespan
        app.state.container = container
    app.add_middleware(RequestIdMiddleware)
    app.include_router(chat_router)
    app.include_router(embeddings_router)

    @app.exception_handler(GatewayError)
    async def _gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> JSONResponse:
        err = GatewayError("invalid_request")
        return JSONResponse(err.body(), status_code=err.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        err = GatewayError("not_found" if exc.status_code == 404 else "invalid_request")
        return JSONResponse(err.body(), status_code=exc.status_code)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Không auth; chỉ báo sống (contracts §1)."""
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics(request: Request) -> Response:
        """Bearer `METRICS_TOKEN` (contracts §1)."""
        token = settings.metrics_token
        got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(got.encode(), token.encode()):
            raise GatewayError("forbidden", "Metrics token required.", status=401)
        c: Container | None = getattr(request.app.state, "container", None)
        body = c.metrics.render() if c else b""
        return Response(body, media_type="text/plain; version=0.0.4")

    return app


app = create_app()
