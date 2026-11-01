"""Request-id + CSP và security headers (contracts §9.3). ASGI thuần để không đệm SSE."""

from __future__ import annotations

import re
from typing import Any

from acme_common.log import bind_request_id, new_request_id, reset_request_id
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)

STATIC_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    ),
}
HSTS = "max-age=31536000; includeSubDomains"
_RID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return None


class RequestContextMiddleware:
    """Gắn `X-Request-Id` + header bảo mật vào MỌI response (kể cả lỗi và SSE)."""

    def __init__(self, app: ASGIApp, *, https: bool) -> None:
        self.app = app
        self._https = https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-request-id")
        rid = incoming if incoming and _RID.match(incoming) else new_request_id()
        scope.setdefault("state", {})["request_id"] = rid
        path: str = scope["path"]
        no_store = path.startswith(("/api/", "/auth/"))
        ctx = bind_request_id(rid)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[Any] = list(message.get("headers", []))
                extra = dict(STATIC_HEADERS)
                extra["X-Request-Id"] = rid
                if self._https:
                    extra["Strict-Transport-Security"] = HSTS
                if no_store:
                    extra["Cache-Control"] = "no-store"
                names = {k.lower().encode() for k in extra}
                headers = [(k, v) for k, v in headers if k.lower() not in names]
                headers.extend((k.encode(), v.encode()) for k, v in extra.items())
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_request_id(ctx)
