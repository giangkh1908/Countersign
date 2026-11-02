"""`POST /v1/rerank` (kiểu Jina/Cohere: `{model, query, documents, top_n}`)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..services.errors import GatewayError
from ..services.rerank import parse_rerank_body
from .chat import container_of, read_json

router = APIRouter()


@router.post("/v1/rerank", response_model=None)
async def rerank(request: Request) -> Response:
    c = container_of(request)
    try:
        caller = await c.auth.authenticate(
            request.headers.get("authorization"), request.headers.get("x-acme-user-token")
        )
    except GatewayError as exc:
        c.metrics.auth_failures.labels(exc.code).inc()
        raise
    parsed = parse_rerank_body(await read_json(request, request.app.state.max_body_bytes))
    done = await c.rerank.rerank(request.state.request_id, caller, parsed)
    return JSONResponse(done.body, headers=done.headers)
