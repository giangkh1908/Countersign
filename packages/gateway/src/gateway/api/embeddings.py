"""`POST /v1/embeddings` (OpenAI-compatible, `encoding_format` float)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..services.embeddings import parse_embeddings_body
from ..services.errors import GatewayError
from .chat import container_of, read_json

router = APIRouter()


@router.post("/v1/embeddings", response_model=None)
async def embeddings(request: Request) -> Response:
    c = container_of(request)
    try:
        caller = await c.auth.authenticate(
            request.headers.get("authorization"), request.headers.get("x-acme-user-token")
        )
    except GatewayError as exc:
        c.metrics.auth_failures.labels(exc.code).inc()
        raise
    parsed = parse_embeddings_body(await read_json(request, request.app.state.max_body_bytes))
    done = await c.embeddings.embed(request.state.request_id, caller, parsed)
    return JSONResponse(done.body, headers=done.headers)
