"""Kiểm Origin cho request đổi trạng thái, và trần kích thước body (07 §2.5, §2.6)."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..services.errors import ApiError, error_body

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_BODY_BYTES = 64 * 1024


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return None


def origin_allowed(origin: str | None, sec_fetch_site: str | None, public_origin: str) -> bool:
    """Có `Origin` thì phải bằng origin công khai; không có thì `Sec-Fetch-Site` same-origin/none."""
    if origin is not None:
        return origin == public_origin
    return sec_fetch_site in {"same-origin", "none"}


class OriginGuardMiddleware:
    def __init__(self, app: ASGIApp, *, public_origin: str) -> None:
        self.app = app
        self._origin = public_origin

    async def _reject(self, scope: Scope, send: Send, err: ApiError) -> None:
        rid = scope.get("state", {}).get("request_id", "")
        body = json.dumps(error_body(err, rid), ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": err.status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        if not origin_allowed(
            _header(scope, b"origin"), _header(scope, b"sec-fetch-site"), self._origin
        ):
            await self._reject(scope, send, ApiError(403, "csrf_failed"))
            return
        length = _header(scope, b"content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            await self._reject(scope, send, ApiError(413, "request_too_large"))
            return

        seen = 0

        async def counted_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    # body chunked vượt trần: cắt cụt để pydantic từ chối (400); không đệm thêm
                    return {"type": "http.request", "body": b"", "more_body": False}
            return msg

        await self.app(scope, counted_receive, send)
