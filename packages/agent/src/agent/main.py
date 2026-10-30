"""Điểm vào ASGI của agent: `uvicorn agent.main:app`.

Không có APPROVAL_SIGNER_URL: agent không được gọi approval-signer (D13).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from acme_common.log import configure_logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.app import ApiError, error_response, router
from .container import Container, build_container
from .settings import Settings


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """`container` tiêm sẵn (test) hoặc None: lifespan dựng từ settings qua factory."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        s = settings or Settings()
        configure_logging(s.log_level, "agent")
        c = container or await build_container(s)
        app.state.container = c
        try:
            yield
        finally:
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
