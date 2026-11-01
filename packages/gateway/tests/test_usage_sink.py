"""Sink hỏng không được làm hỏng request; vòng flush định kỳ chạy và dừng sạch."""

from __future__ import annotations

import asyncio

from acme_common.ports import EventSink
from acme_common.ports.event_sink import EventRecord
from gateway.container import Container
from gateway.main import _flush_loop
from gw_support import Env


class _BrokenSink(EventSink):
    def append(self, record: EventRecord, sync: bool = False) -> None:
        raise RuntimeError("db down")

    async def flush(self, timeout_s: float = 5.0) -> None:
        raise RuntimeError("db down")


async def test_request_succeeds_when_sink_append_fails(env: Env, api_key: str) -> None:
    env.app.state.container.chat._sink = _BrokenSink()  # noqa: SLF001
    async with env.gateway_client(api_key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "acme-fast", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200


async def test_usage_event_has_contract_fields(env: Env, api_key: str) -> None:
    async with env.gateway_client(api_key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "acme-fast", "messages": [{"role": "user", "content": "hi"}]},
        )
    ev = [e for e in env.sink.events if e["event"] == "usage_event"][0]
    assert ev["request_id"] == r.headers["x-acme-request-id"]
    for f in ("key_id", "department", "alias", "provider", "input_tokens", "output_tokens",
              "cost_micro_usd", "latency_ms", "status_code"):  # fmt: skip
        assert f in ev


async def test_flush_loop_survives_failures_and_can_be_cancelled(env: Env) -> None:
    c: Container = env.app.state.container
    c.sink = _BrokenSink()
    task = asyncio.create_task(_flush_loop(c, 0.01))
    await asyncio.sleep(0.05)
    assert not task.done()  # lỗi flush không giết vòng lặp
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_flush_loop_calls_flush(env: Env) -> None:
    c: Container = env.app.state.container
    task = asyncio.create_task(_flush_loop(c, 0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert env.sink.flushed >= 1
