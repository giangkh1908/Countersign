"""Unit: crypto, CSRF, relay SSE (từng chunk, heartbeat, timeout, huỷ), parser, errors."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from bff.services.crypto import Crypto, CryptoError
from bff.services.csrf import csrf_valid
from bff.services.errors import ApiError, UpstreamStatus, to_http_error
from bff.services.sse_proxy import (
    FrameTooLarge,
    SseFrame,
    json_frame,
    parse_frames,
    relay,
)

KEY = bytes(range(32))


def test_crypto_roundtrip_and_aad_binding() -> None:
    c = Crypto(KEY)
    sealed = c.seal("refresh-secret", sid="s1", field="refresh_token_enc")
    assert "refresh-secret" not in sealed
    assert c.open(sealed, sid="s1", field="refresh_token_enc") == "refresh-secret"
    with pytest.raises(CryptoError):
        c.open(sealed, sid="s2", field="refresh_token_enc")  # sai sid
    with pytest.raises(CryptoError):
        c.open(sealed, sid="s1", field="access_enc")  # sai tên trường
    with pytest.raises(CryptoError):
        Crypto(bytes(reversed(KEY))).open(sealed, sid="s1", field="refresh_token_enc")
    assert c.seal("x", sid="s", field="f") != c.seal("x", sid="s", field="f")  # nonce ngẫu nhiên


def test_csrf_bound_to_session() -> None:
    c = Crypto(KEY)
    tok = c.csrf_for("sid-a")
    assert csrf_valid(c, sid="sid-a", header=tok, cookie=tok)
    assert not csrf_valid(c, sid="sid-b", header=tok, cookie=tok)
    assert not csrf_valid(c, sid="sid-a", header=tok, cookie=None)
    assert not csrf_valid(c, sid="sid-a", header=None, cookie=tok)


async def _lines(text: str) -> AsyncIterator[str]:
    for line in text.split("\n"):
        yield line


async def test_parse_frames_handles_comments_multiline_data_and_ids() -> None:
    text = ": ping\n\nid: 1\nevent: token\ndata: a\ndata: b\n\ndata: only\n\n"
    frames = [f async for f in parse_frames(_lines(text.rstrip("\n") + "\n"))]
    assert frames[0].comment == "ping"
    assert (frames[1].id, frames[1].event, frames[1].data) == ("1", "token", "a\nb")
    assert (frames[2].event, frames[2].data) == ("message", "only")
    assert (
        SseFrame(event="e", data="a\nb", id="3").encode()
        == b"id: 3\nevent: e\ndata: a\ndata: b\n\n"
    )


async def test_parse_frames_rejects_oversized_frame() -> None:
    async def big() -> AsyncIterator[str]:
        for _ in range(100):
            yield "data: " + "x" * 1000

    with pytest.raises(FrameTooLarge):
        _ = [f async for f in parse_frames(big())]


async def _keep(fr: SseFrame) -> SseFrame | None:
    return fr


async def test_relay_forwards_each_frame_before_upstream_finishes() -> None:
    gate = asyncio.Event()
    closed = asyncio.Event()

    async def upstream() -> AsyncIterator[SseFrame]:
        try:
            yield json_frame("token", {"text": "a"})
            await gate.wait()
            yield json_frame("done", {"status": "completed"})
        finally:
            closed.set()

    it = relay(upstream(), _keep, heartbeat_s=5)
    first = await asyncio.wait_for(it.__anext__(), 1)
    assert b"event: token" in first and not closed.is_set()
    gate.set()
    second = await asyncio.wait_for(it.__anext__(), 1)
    assert b"event: done" in second
    with pytest.raises(StopAsyncIteration):
        await it.__anext__()
    assert closed.is_set()


async def test_relay_emits_keepalive_then_idle_timeout() -> None:
    async def silent() -> AsyncIterator[SseFrame]:
        await asyncio.sleep(10)
        yield json_frame("done", {})

    out = [c async for c in relay(silent(), _keep, heartbeat_s=0.02, idle_s=0.07, max_s=5)]
    assert out[0] == b": keepalive\n\n"
    last = json.loads(out[-1].split(b"data: ")[1])
    assert last["code"] == "upstream_timeout" and last["retryable"] is True
    assert out[-1].startswith(b"event: error")


async def test_relay_enforces_max_duration() -> None:
    async def slow() -> AsyncIterator[SseFrame]:
        while True:
            await asyncio.sleep(0.01)
            yield SseFrame(comment="ping")

    out = [c async for c in relay(slow(), _keep, heartbeat_s=0.02, idle_s=5, max_s=0.1)]
    assert b"upstream_timeout" in out[-1]


async def test_relay_cancel_closes_upstream() -> None:
    closed = asyncio.Event()

    async def upstream() -> AsyncIterator[SseFrame]:
        try:
            yield json_frame("token", {"text": "a"})
            await asyncio.sleep(10)
            yield json_frame("done", {})
        finally:
            closed.set()

    gen = relay(upstream(), _keep, heartbeat_s=5)
    await gen.__anext__()
    await gen.aclose()  # trình duyệt ngắt ⇒ ASGI đóng generator
    assert closed.is_set()


async def test_relay_prefix_and_stop_after_terminal() -> None:
    async def upstream() -> AsyncIterator[SseFrame]:
        yield json_frame("done", {"status": "completed"})
        yield json_frame("token", {"text": "không được tới"})

    out = [
        c async for c in relay(upstream(), _keep, prefix=[json_frame("thread", {"thread_id": "t"})])
    ]
    assert [c.split(b"\n")[0] for c in out] == [b"event: thread", b"event: done"]


def test_error_mapping_table() -> None:
    cases = [
        (UpstreamStatus("agent", 404), 404, "not_found"),
        (UpstreamStatus("agent", 409), 409, "conflict"),
        (UpstreamStatus("agent", 429, retry_after="7"), 429, "rate_limited"),
        (UpstreamStatus("agent", 503), 502, "upstream_unavailable"),
        (UpstreamStatus("signer", 422, "intent_unrenderable"), 422, "intent_unrenderable"),
        (UpstreamStatus("signer", 422, "intent_mismatch"), 422, "intent_mismatch"),
        (UpstreamStatus("signer", 410), 410, "intent_expired"),
        (UpstreamStatus("signer", 403), 403, "forbidden"),
        (ValueError("boom"), 500, "internal"),
    ]
    for exc, status, code in cases:
        err = to_http_error(exc)
        assert (err.status, err.code) == (status, code), exc
    assert to_http_error(UpstreamStatus("agent", 429, retry_after="7")).headers == {
        "Retry-After": "7"
    }
    assert isinstance(to_http_error(ApiError(418, "internal")), ApiError)
