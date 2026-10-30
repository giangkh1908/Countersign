"""Router chat/SSE và resume. Mỏng, gọi services. Docs: 07 §2.6, §2.8."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..factory import Container
from ..services.session import SessionData
from .deps import get_container, llm_session

router = APIRouter()

Id64 = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
SSE_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}


def sse_response(chunks: AsyncIterator[bytes]) -> StreamingResponse:
    return StreamingResponse(chunks, media_type="text/event-stream", headers=SSE_HEADERS)


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID | None = None
    text: str = Field(min_length=1, max_length=8000)
    client_msg_id: UUID


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["edit", "reject", "refresh", "approve"]
    edits: (
        dict[
            Annotated[str, StringConstraints(max_length=64)],
            Annotated[str, StringConstraints(max_length=4000)],
        ]
        | None
    ) = Field(default=None, max_length=10)
    reason: str | None = Field(default=None, max_length=500)


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID
    interrupt_id: Id64
    decision: DecisionBody


@router.post("/api/chat")
async def chat(
    body: ChatBody,
    s: SessionData = Depends(llm_session),
    c: Container = Depends(get_container),
) -> StreamingResponse:
    chunks = await c.streams.chat(
        s, str(body.thread_id) if body.thread_id else None, body.text, str(body.client_msg_id)
    )
    return sse_response(chunks)


@router.post("/api/resume")
async def resume(
    body: ResumeBody,
    s: SessionData = Depends(llm_session),
    c: Container = Depends(get_container),
) -> StreamingResponse:
    decision: dict[str, Any] = body.decision.model_dump(exclude_none=True)
    chunks = await c.streams.resume(s, str(body.thread_id), body.interrupt_id, decision)
    return sse_response(chunks)
