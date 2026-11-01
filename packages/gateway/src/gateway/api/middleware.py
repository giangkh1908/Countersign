"""ASGI middleware thuần: gắn request id vào mọi response (kể cả 500) và trả lại `X-Acme-Client-Request-Id`."""

from __future__ import annotations

import json
import logging
import re
import uuid

from acme_common.log import bind_request_id, reset_request_id
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..services.errors import GatewayError

log = logging.getLogger("gateway.http")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        client_id: str | None = None
        for k, v in scope["headers"]:
            if k == b"x-acme-client-request-id":
                cand = v.decode("latin-1")
                client_id = cand if _CLIENT_ID_RE.match(cand) else None
        scope.setdefault("state", {})["request_id"] = request_id
        extra = [(b"x-acme-request-id", request_id.encode())]
        if client_id:
            extra.append((b"x-acme-client-request-id", client_id.encode()))
        started = False

        async def wrapped(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        token = bind_request_id(request_id)
        try:
            await self.app(scope, receive, wrapped)
        except Exception:
            log.exception("unhandled error")
            if started:
                raise
            err = GatewayError("internal_error")
            body = json.dumps(err.body()).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": err.status,
                    "headers": [(b"content-type", b"application/json"), *extra],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            reset_request_id(token)
