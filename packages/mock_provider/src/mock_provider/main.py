"""Entrypoint FastAPI của mock_provider: `uvicorn mock_provider.main:app`.

Vận hành: `GET /healthz` (không auth), `GET /metrics` (Bearer METRICS_TOKEN, contracts §1),
`/__control` (chaos theo scope, Bearer MOCK_CONTROL_TOKEN nếu có cấu hình).
"""

from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .behavior import Context
from .factory import build_router, wire_names
from .settings import Settings

SCOPES = {"*", *wire_names()}


class _CountRequests:
    """ASGI middleware đếm request theo (route, status)."""

    def __init__(self, app: ASGIApp, ctx: Context) -> None:
        self.app, self.ctx = app, ctx

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                route = scope.get("route")
                self.ctx.count(getattr(route, "path", scope["path"]), message["status"])
            await send(message)

        await self.app(scope, receive, wrapped)


def _bearer(request: Request) -> str:
    return request.headers.get("authorization", "").removeprefix("Bearer ").strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    ctx = Context(settings)
    app = FastAPI(title="Mock Provider")
    app.state.ctx = ctx
    app.add_middleware(_CountRequests, ctx=ctx)
    for name in wire_names():
        app.include_router(build_router(name, ctx))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Không auth; chỉ báo sống (contracts §1)."""
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(request: Request) -> str:
        token = settings.metrics_token
        if not token or _bearer(request) != token:
            raise HTTPException(401, "metrics token required")
        lines = ["# TYPE mock_requests_total counter"]
        for (route, status), n in sorted(ctx.stats.items()):
            lines.append(f'mock_requests_total{{route="{route}",status="{status}"}} {n}')
        return "\n".join(lines) + "\n"

    def control_guard(request: Request) -> None:
        token = settings.control_token
        if token and _bearer(request) != token:
            raise HTTPException(401, "control token required")

    @app.get("/__control")
    def control_get(request: Request) -> dict[str, Any]:
        control_guard(request)
        return {"overrides": ctx.overrides, "requests_planned": ctx.counter}

    @app.put("/__control/{scope}")
    def control_put(
        scope: str, request: Request, overrides: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Ghi đè hành vi cho scope (tên wire hoặc `*`); cùng tên field như header."""
        control_guard(request)
        if scope not in SCOPES:
            raise HTTPException(404, f"scope không hợp lệ; hợp lệ: {sorted(SCOPES)}")
        ctx.overrides.setdefault(scope, {}).update(overrides)
        return {"overrides": ctx.overrides}

    @app.delete("/__control")
    def control_reset(request: Request) -> dict[str, str]:
        control_guard(request)
        ctx.reset()
        return {"status": "reset"}

    return app


app = create_app()
