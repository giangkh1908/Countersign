"""HTTP API nội bộ của agent cho BFF (03 §1.3). Lỗi: `{"error":{"code","message","retryable"}}`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from acme_common.ports import Principal, TokenInvalid, TokenServiceUnavailable
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from .container import Container
from .graph.nodes import Decision
from .run_service import (
    Event,
    config_of,
    pending_interrupt,
    resume_input,
    run_input,
    stream_run,
)

HEARTBEAT_S = 15.0


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "", retryable: bool = False) -> None:
        self.status, self.code, self.message, self.retryable = (
            status,
            code,
            message or code,
            retryable,
        )


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable}},
        status_code=exc.status,
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


class Caller:
    def __init__(self, principal: Principal, token: str) -> None:
        self.principal, self.token = principal, token


ContDep = Annotated[Container, Depends(get_container)]


async def authenticate(request: Request, c: ContDep) -> Caller:
    """Verify token `aud=agent-service` (azp/scope theo cấu hình verifier). Sai aud => 403, hỏng => 401."""
    h = request.headers.get("authorization", "")
    scheme, _, token = h.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "unauthorized", "Missing bearer token.")
    try:
        p = await c.verifier.verify(token.strip(), c.settings.agent_audience)
    except TokenInvalid as e:
        raise ApiError(
            e.http_status,
            "unauthorized" if e.http_status == 401 else "forbidden",
            "Token rejected.",
        ) from None
    except TokenServiceUnavailable:
        raise ApiError(503, "upstream_unavailable", "Identity service unavailable.", True) from None
    return Caller(p, token.strip())


AuthDep = Annotated[Caller, Depends(authenticate)]


class CreateThread(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RunBody(BaseModel):
    class Input(BaseModel):
        text: str = Field(min_length=1, max_length=16000)

    input: Input
    client_msg_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ResumeBody(BaseModel):
    interrupt_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    decision: dict[str, Any]


def sse_frame(seq: int, event: str, data: dict[str, Any]) -> bytes:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def sse_response(
    events: AsyncIterator[Event], on_close: Callable[[], Awaitable[None]]
) -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        q: asyncio.Queue[Event | None] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for ev in events:
                    await q.put(ev)
            finally:
                await q.put(None)

        task = asyncio.create_task(produce())
        seq = 0
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), HEARTBEAT_S)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if ev is None:
                    break
                seq += 1
                yield sse_frame(seq, *ev)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await on_close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _owned(c: Container, caller: Caller, thread_id: UUID) -> str:
    tid = str(thread_id)
    if await c.repo.get(tid, caller.principal.sub) is None:
        raise ApiError(404, "not_found", "Thread not found.")
    return tid


def _lock(c: Container, tid: str) -> asyncio.Lock:
    lock = c.locks.setdefault(tid, asyncio.Lock())
    if lock.locked():
        raise ApiError(409, "conflict", "Thread is busy.")
    return lock


router = APIRouter(prefix="/v1")


@router.post("/threads", status_code=201)
async def create_thread(body: CreateThread, caller: AuthDep, c: ContDep) -> dict[str, Any]:
    conv = await c.repo.create(caller.principal.sub, body.title)
    return {"thread_id": conv.thread_id, "created_at": conv.created_at.isoformat()}


@router.get("/threads")
async def list_threads(caller: AuthDep, c: ContDep, limit: int = 20) -> dict[str, Any]:
    rows = await c.repo.list(caller.principal.sub, max(1, min(limit, 100)))
    return {
        "items": [
            {
                "thread_id": r.thread_id,
                "title": r.title,
                "last_active_at": r.last_active_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/threads/{thread_id}/messages")
async def messages(thread_id: UUID, caller: AuthDep, c: ContDep) -> dict[str, Any]:
    tid = await _owned(c, caller, thread_id)
    snap = await c.graph.aget_state(config_of(tid))
    values = snap.values or {}
    out = []
    for m in values.get("messages", []):
        if m.type in ("human", "ai") and isinstance(m.content, str) and m.content:
            out.append(
                {
                    "id": m.id,
                    "role": "user" if m.type == "human" else "assistant",
                    "content": m.content,
                }
            )
    return {
        "messages": out,
        "pending_interrupt": pending_interrupt(snap),
        "cost": {"thread_usd": values.get("cost_usd", 0.0)},
    }


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: UUID, caller: AuthDep, c: ContDep) -> Response:
    tid = await _owned(c, caller, thread_id)
    await c.checkpointer.adelete_thread(tid)
    await c.repo.mark_deleted(tid, caller.principal.sub)
    return Response(status_code=204)


@router.post("/threads/{thread_id}/runs")
async def run(thread_id: UUID, body: RunBody, caller: AuthDep, c: ContDep) -> StreamingResponse:
    tid = await _owned(c, caller, thread_id)
    lock = _lock(c, tid)
    await lock.acquire()
    try:
        snap = await c.graph.aget_state(config_of(tid))
        if pending_interrupt(snap):
            raise ApiError(409, "conflict", "Thread is waiting for a decision.")
        if any(m.id == body.client_msg_id for m in (snap.values or {}).get("messages", [])):
            raise ApiError(409, "conflict", "Duplicate client_msg_id.")
    except BaseException:
        lock.release()
        raise
    events = stream_run(
        c, caller.principal, caller.token, tid, run_input(body.input.text, body.client_msg_id)
    )
    return sse_response(events, _release(lock))


@router.post("/threads/{thread_id}/resume")
async def resume(
    thread_id: UUID, body: ResumeBody, caller: AuthDep, c: ContDep
) -> StreamingResponse:
    tid = await _owned(c, caller, thread_id)
    try:
        decision = Decision.model_validate(body.decision).model_dump()
    except ValidationError:
        raise ApiError(400, "invalid_request", "Invalid decision.") from None
    lock = _lock(c, tid)
    await lock.acquire()
    try:
        pend = pending_interrupt(await c.graph.aget_state(config_of(tid)))
        if pend is None or pend["interrupt_id"] != body.interrupt_id:
            raise ApiError(409, "conflict", "No matching interrupt.")
    except BaseException:
        lock.release()
        raise
    events = stream_run(c, caller.principal, caller.token, tid, resume_input(decision))
    return sse_response(events, _release(lock))


def _release(lock: asyncio.Lock) -> Callable[[], Awaitable[None]]:
    async def release() -> None:
        if lock.locked():
            lock.release()

    return release


@router.post("/internal/evict", status_code=204)
async def evict(caller: AuthDep) -> Response:
    # Cache token exchange nằm trong CachingTokenBroker (acme_common) chưa có evict(sub); token tự hết hạn <=300s.
    return Response(status_code=204)
