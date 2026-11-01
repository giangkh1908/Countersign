"""StreamService: mở luồng tới agent (chat/resume/approve) và relay SSE về trình duyệt (07 §2.8)."""

from __future__ import annotations

import contextlib
import json
import unicodedata
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..adapters.agent_client import AgentClient
from .approval_flow import ApprovalFlow, CardBlocked
from .rate_limit import RateLimits
from .session import SessionData
from .sse_proxy import SseFrame, error_frame, json_frame, relay, upstream_frames
from .tokens import TokenService


def make_title(text: str) -> str:
    cleaned = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch == " ")
    return " ".join(cleaned.split())[:60]


class StreamService:
    def __init__(
        self,
        tokens: TokenService,
        agent: AgentClient,
        flow: ApprovalFlow,
        limits: RateLimits,
        *,
        heartbeat_s: float,
        idle_s: float,
        max_s: float,
    ) -> None:
        self._tokens = tokens
        self._agent = agent
        self._flow = flow
        self._limits = limits
        self._hb, self._idle, self._max = heartbeat_s, idle_s, max_s

    async def chat(
        self, s: SessionData, thread_id: str | None, text: str, client_msg_id: str
    ) -> AsyncIterator[bytes]:
        await self._limits.acquire_stream(s.sid)
        try:
            prefix: list[SseFrame] = []
            if thread_id is None:
                title = make_title(text)
                created = await self._tokens.call(
                    s, "agent", lambda tok: self._agent.create_thread(tok, title)
                )
                thread_id = str(created["thread_id"])
                prefix.append(json_frame("thread", {"thread_id": thread_id, "title": title}))
            tid = thread_id
            resp = await self._tokens.call(
                s, "agent", lambda tok: self._agent.run(tok, tid, text, client_msg_id)
            )
        except BaseException:
            await self._limits.release_stream(s.sid)
            raise
        return self._stream(s, tid, resp, prefix)

    async def approve(
        self, s: SessionData, thread_id: str, interrupt_id: str, intent_sha256: str
    ) -> AsyncIterator[bytes]:
        await self._limits.acquire_stream(s.sid)
        try:
            resp, expires_at = await self._flow.approve(s, thread_id, interrupt_id, intent_sha256)
        except BaseException:
            await self._limits.release_stream(s.sid)
            raise
        prefix = [json_frame("approval", {"expires_at": expires_at})]
        return self._stream(s, thread_id, resp, prefix)

    async def resume(
        self, s: SessionData, thread_id: str, interrupt_id: str, decision: dict[str, Any]
    ) -> AsyncIterator[bytes]:
        await self._limits.acquire_stream(s.sid)
        try:
            resp = await self._flow.decide(s, thread_id, interrupt_id, decision)
        except BaseException:
            await self._limits.release_stream(s.sid)
            raise
        return self._stream(s, thread_id, resp, [])

    async def _on_frame(self, s: SessionData, thread_id: str, fr: SseFrame) -> SseFrame | None:
        if fr.event != "interrupt":
            return fr
        try:
            public = await self._flow.register(s, thread_id, json.loads(fr.data))
        except CardBlocked as blocked:
            if blocked.reason == "intent_rejected_recently":
                return error_frame("conflict", reason=blocked.reason)
            return error_frame("rate_limited", reason=blocked.reason)
        except (ValueError, TypeError, AttributeError):
            return error_frame("upstream_unavailable", retryable=True)
        return SseFrame(event="interrupt", data=json.dumps(public, separators=(",", ":")), id=fr.id)

    async def _stream(
        self, s: SessionData, thread_id: str, resp: httpx.Response, prefix: list[SseFrame]
    ) -> AsyncIterator[bytes]:
        async def on_frame(fr: SseFrame) -> SseFrame | None:
            return await self._on_frame(s, thread_id, fr)

        try:
            async with contextlib.aclosing(
                relay(
                    upstream_frames(resp),
                    on_frame,
                    heartbeat_s=self._hb,
                    idle_s=self._idle,
                    max_s=self._max,
                    prefix=prefix,
                )
            ) as chunks:
                async for chunk in chunks:
                    yield chunk
        finally:
            await resp.aclose()
            await self._limits.release_stream(s.sid)
