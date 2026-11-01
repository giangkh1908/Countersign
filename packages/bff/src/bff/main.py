"""Điểm vào ASGI của bff: `uvicorn bff.main:app` (app dựng lười lúc import thuộc tính `app`)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from acme_common.http import HttpError
from acme_common.log import configure_logging
from acme_common.ports import TokenExchangeDenied, TokenInvalid, TokenServiceUnavailable
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import approvals, auth, chat, health, me, threads
from .api.headers import RequestContextMiddleware
from .api.origin import OriginGuardMiddleware
from .factory import Container, build_container
from .services.crypto import CryptoError
from .services.errors import ApiError, UpstreamStatus, error_body, to_http_error
from .settings import Settings

log = logging.getLogger("bff")

_MAPPED_EXCEPTIONS: tuple[type[Exception], ...] = (
    UpstreamStatus,
    TokenExchangeDenied,
    TokenServiceUnavailable,
    TokenInvalid,
    HttpError,
    RedisError,
    CryptoError,
)


def _rid(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def _json_error(request: Request, err: ApiError) -> JSONResponse:
    return JSONResponse(
        error_body(err, _rid(request)), status_code=err.status, headers=err.headers or None
    )


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError) -> JSONResponse:
        return _json_error(request, exc)

    async def _mapped(request: Request, exc: Exception) -> JSONResponse:
        return _json_error(request, to_http_error(exc))

    for exc_type in _MAPPED_EXCEPTIONS:
        app.add_exception_handler(exc_type, _mapped)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _json_error(request, ApiError(400, "invalid_request"))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "invalid_request"}.get(exc.status_code, "internal")
        status = exc.status_code if exc.status_code in (404, 405) else 500
        return _json_error(request, ApiError(status, code))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return _json_error(request, to_http_error(exc))


def _mount_spa(app: FastAPI, static_dir: str) -> None:
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "auth/")) or path in {"api", "auth"}:
            raise StarletteHTTPException(404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            immutable = path.startswith("assets/")
            return FileResponse(
                candidate,
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable"
                    if immutable
                    else "no-cache"
                },
            )
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(
    settings: Settings | None = None, *, container: Container | None = None, **overrides: Any
) -> FastAPI:
    """`container`/`overrides` (redis, clock, verifier, broker, transport) dùng cho test."""
    settings = settings or Settings()
    container = container or build_container(settings, **overrides)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await container.aclose()

    app = FastAPI(title="bff", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.container = container
    # thứ tự: middleware thêm sau cùng là ngoài cùng
    app.add_middleware(OriginGuardMiddleware, public_origin=settings.public_origin)
    app.add_middleware(RequestContextMiddleware, https=settings.https)
    _install_error_handlers(app)
    for module in (health, auth, me, chat, threads, approvals):
        app.include_router(module.router)
    if settings.bff_static_dir:
        _mount_spa(app, settings.bff_static_dir)
    return app


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        configure_logging(Settings().log_level, "bff")
        instance = create_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(name)
