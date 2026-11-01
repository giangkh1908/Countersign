"""Điểm vào ASGI của agent: `uvicorn agent.main:app`.

Không có APPROVAL_SIGNER_URL: agent không được gọi approval-signer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from acme_common.log import configure_logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import ApiError, error_response, router
from .container import Container, build_container, refresh_optional_agents
from .factory import build_service_probe
from .settings import Settings

log = logging.getLogger(__name__)


async def _watch_optional_agents(c: Container, s: Settings) -> None:
    """Agent tuỳ chọn (ticket) đang tắt: dò lại định kỳ để bật khi MCP của nó lên sau agent."""
    probe = build_service_probe(s.service_probe_adapter, s)
    while True:
        await asyncio.sleep(s.optional_agents_recheck_s)
        try:
            if await refresh_optional_agents(c, probe):
                log.info(
                    "optional_agents_changed",
                    extra={"fields": {"agents": c.settings.agents_enabled}},
                )
        except Exception:  # không để watcher chết làm sập agent
            log.exception("optional_agents_refresh_failed")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """`container` tiêm sẵn (test) hoặc None: lifespan dựng từ settings qua factory."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        s = settings or Settings()
        configure_logging(s.log_level, "agent")
        c = container or await build_container(s)
        app.state.container = c
        watcher = None
        if container is None and s.optional_agents_recheck_s > 0:
            watcher = asyncio.create_task(_watch_optional_agents(c, s))
        try:
            yield
        finally:
            if watcher is not None:
                watcher.cancel()
            for close in c.closers:
                await close()

    app = FastAPI(title="agent", lifespan=lifespan)
    if container is not None:  # test dùng ASGITransport không chạy lifespan
        app.state.container = container
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(ApiError(400, "invalid_request", "Invalid request."))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
