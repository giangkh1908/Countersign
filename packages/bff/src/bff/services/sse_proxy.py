"""SseProxy: phân tích khung SSE, lọc event, giữ nhịp, giới hạn thời gian, huỷ (07 §2.8).

Chỉ đọc khung `id`/`event`/`data`; mọi event hợp lệ khác chuyển nguyên văn. Luồng luôn kết thúc
bằng đúng một `done` hoặc `error`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import httpx

from .errors import message_for

MAX_FRAME_BYTES = 64 * 1024
ALLOWED_EVENTS = frozenset(
    {
        "run_start",
        "route",
        "token",
        "tool_start",
        "tool_end",
        "interrupt",
        "citations",
        "cost",
        "done",
        "error",
        "thread",
        "approval",
    }
)
TERMINAL_EVENTS = frozenset({"done", "error"})


@dataclass
class SseFrame:
    event: str = "message"
    data: str = ""
    id: str | None = None
    comment: str | None = None  # khung chỉ có dòng chú thích (heartbeat `: ping`)

    def encode(self) -> bytes:
        if self.comment is not None:
            return f": {self.comment}\n\n".encode()
        lines = []
        if self.id is not None:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")
        lines.extend(f"data: {part}" for part in (self.data.split("\n") or [""]))
        return ("\n".join(lines) + "\n\n").encode()


def json_frame(event: str, payload: dict[str, object]) -> SseFrame:
    return SseFrame(
        event=event, data=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def error_frame(code: str, *, retryable: bool = False, **extra: object) -> SseFrame:
    return json_frame(
        "error", {"code": code, "message": message_for(code), "retryable": retryable, **extra}
    )


class FrameTooLarge(Exception):
    pass


async def parse_frames(lines: AsyncIterator[str]) -> AsyncIterator[SseFrame]:
    """Gom dòng SSE thành khung. Dòng trống kết thúc khung."""
    event, data, fid, comments, size = "message", [], None, [], 0
    async for line in lines:
        size += len(line) + 1
        if size > MAX_FRAME_BYTES:
            raise FrameTooLarge()
        if line == "":
            if data or event != "message" or fid is not None:
                yield SseFrame(event=event, data="\n".join(data), id=fid)
            elif comments:
                yield SseFrame(comment=comments[0])
            event, data, fid, comments, size = "message", [], None, [], 0
            continue
        if line.startswith(":"):
            comments.append(line[1:].strip())
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
        elif name == "id":
            fid = value


async def upstream_frames(resp: httpx.Response) -> AsyncIterator[SseFrame]:
    try:
        async for fr in parse_frames(resp.aiter_lines()):
            yield fr
    finally:
        await resp.aclose()


OnFrame = Callable[[SseFrame], Awaitable[SseFrame | None]]


async def relay(
    upstream: AsyncIterator[SseFrame],
    on_frame: OnFrame,
    *,
    heartbeat_s: float = 15.0,
    idle_s: float = 45.0,
    max_s: float = 300.0,
    prefix: list[SseFrame] | None = None,
) -> AsyncIterator[bytes]:
    """Chuyển từng khung ngay khi nhận. `on_frame` trả khung đã lọc/viết lại hoặc None (bỏ)."""
    for fr in prefix or []:
        yield fr.encode()
    t0 = last = time.monotonic()
    pending: asyncio.Future[SseFrame] | None = None
    terminal = False
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(upstream.__anext__())  # type: ignore[arg-type]
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
            now = time.monotonic()
            if not done:
                if now - last > idle_s or now - t0 > max_s:
                    yield error_frame("upstream_timeout", retryable=True).encode()
                    terminal = True
                    return
                yield b": keepalive\n\n"
                continue
            try:
                fr = pending.result()
            except StopAsyncIteration:
                break
            except FrameTooLarge:
                yield error_frame("upstream_unavailable", retryable=True).encode()
                terminal = True
                return
            except (httpx.HTTPError, OSError):
                break
            finally:
                pending = None
            last = now
            if now - t0 > max_s:
                yield error_frame("upstream_timeout", retryable=True).encode()
                terminal = True
                return
            if fr.comment is not None:
                yield fr.encode()
                continue
            if fr.event not in ALLOWED_EVENTS:
                continue
            out = await on_frame(fr)
            if out is None:
                continue
            yield out.encode()
            if out.event in TERMINAL_EVENTS:
                terminal = True
                return
        if not terminal:
            yield error_frame("upstream_unavailable", retryable=True).encode()
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pending
        aclose = getattr(upstream, "aclose", None)
        if aclose is not None:
            await aclose()
