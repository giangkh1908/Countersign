"""`POST /v1/chat/completions` (OpenAI-compatible; non-stream và SSE)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..container import Container
from ..services.chat import parse_chat_body
from ..services.errors import GatewayError

router = APIRouter()


def container_of(request: Request) -> Container:
    c = getattr(request.app.state, "container", None)
    if c is None:
        raise GatewayError("service_unavailable")
    return c


async def read_json(request: Request, max_bytes: int) -> Any:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise GatewayError("request_too_large")
    raw = await request.body()
    if len(raw) > max_bytes:
        raise GatewayError("request_too_large")
    try:
        return json.loads(raw)
    except ValueError:
        raise GatewayError("invalid_request", "Body is not valid JSON.") from None


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> Response:
    c = container_of(request)
    try:
        caller = await c.auth.authenticate(
            request.headers.get("authorization"), request.headers.get("x-acme-user-token")
        )
    except GatewayError as exc:
        c.metrics.auth_failures.labels(exc.code).inc()
        raise
    max_bytes = request.app.state.max_body_bytes
    parsed = parse_chat_body(await read_json(request, max_bytes))
    request_id: str = request.state.request_id
    if parsed.stream:
        res = await c.chat.stream(request_id, caller, parsed)
        return StreamingResponse(
            res.events,
            media_type="text/event-stream",
            headers={**res.headers, "cache-control": "no-cache", "x-accel-buffering": "no"},
        )
    done = await c.chat.complete(request_id, caller, parsed)
    return JSONResponse(done.body, headers=done.headers)
