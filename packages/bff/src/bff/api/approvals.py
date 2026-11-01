"""Router phê duyệt: verify thẻ + approve. Mỏng, gọi services."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints

from ..factory import Container
from ..services.approval_flow import CardModel
from ..services.session import SessionData
from .chat import Id64, sse_response
from .deps import get_container, llm_session, write_session

router = APIRouter()


class VerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID
    interrupt_id: Id64


class ApproveBody(VerifyBody):
    intent_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


@router.post("/api/intents/verify")
async def verify(
    body: VerifyBody,
    s: SessionData = Depends(write_session),
    c: Container = Depends(get_container),
) -> CardModel:
    return await c.flow.verify(s, str(body.thread_id), body.interrupt_id)


@router.post("/api/approvals")
async def approve(
    body: ApproveBody,
    s: SessionData = Depends(llm_session),
    c: Container = Depends(get_container),
) -> StreamingResponse:
    chunks = await c.streams.approve(s, str(body.thread_id), body.interrupt_id, body.intent_sha256)
    return sse_response(chunks)
