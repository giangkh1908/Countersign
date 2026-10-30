"""Router threads và chi phí request. Mỏng, gọi services. Docs: 07 §2.6."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from ..factory import Container
from ..services.approval_flow import CardBlocked
from ..services.errors import ApiError
from ..services.session import SessionData
from .deps import get_container, read_session, write_session

router = APIRouter()

_COST_KEYS = ("request_id", "cost_usd", "alias", "tokens_in", "tokens_out", "cache")


@router.get("/api/threads")
async def list_threads(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[str | None, Query(max_length=128)] = None,
    s: SessionData = Depends(read_session),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    raw = await c.tokens.call(s, "agent", lambda tok: c.agent.list_threads(tok, limit, before))
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ApiError(502, "upstream_unavailable", True)
    next_before = None
    if len(items) >= limit and isinstance(items[-1], dict):
        next_before = items[-1].get("last_active_at")
    return {"items": items, "next_before": next_before}


@router.get("/api/threads/{thread_id}/messages")
async def messages(
    thread_id: UUID,
    s: SessionData = Depends(read_session),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    tid = str(thread_id)
    body = await c.tokens.call(s, "agent", lambda tok: c.agent.messages(tok, tid))
    pending = body.get("pending_interrupt")
    public = None
    if pending:
        try:
            public = await c.flow.register(s, tid, pending)  # bỏ intent_jws
        except CardBlocked:
            public = None
        except (ValueError, TypeError, AttributeError):
            raise ApiError(502, "upstream_unavailable", True) from None
    return {
        "messages": body.get("messages", []),
        "pending_interrupt": public,
        "cost": body.get("cost", {}),
    }


@router.delete("/api/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: UUID,
    s: SessionData = Depends(write_session),
    c: Container = Depends(get_container),
) -> Response:
    tid = str(thread_id)
    await c.tokens.call(s, "agent", lambda tok: c.agent.delete_thread(tok, tid))
    return Response(status_code=204)


@router.get("/api/requests/{request_id}")
async def request_cost(
    request_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    s: SessionData = Depends(read_session),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    body = await c.tokens.call(s, "agent", lambda tok: c.agent.request_cost(tok, request_id))
    if not isinstance(body, dict):
        raise ApiError(502, "upstream_unavailable", True)
    return {k: body[k] for k in _COST_KEYS if k in body}
