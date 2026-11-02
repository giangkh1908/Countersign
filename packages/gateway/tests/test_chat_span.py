"""Span `gen_ai.chat`: model, token, cache, finish_reason; không nội dung prompt/response."""

from __future__ import annotations

import pytest
from acme_common import telemetry
from gw_support import Env
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

CANARY = "CANARY-5b2e-cau-hoi"


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(telemetry.AllowlistSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *_a, **_k: provider.get_tracer("t"))
    return exp


def _body(**extra: object) -> dict[str, object]:
    return {
        "model": "acme-fast",
        "messages": [{"role": "user", "content": f"cau hoi {CANARY}"}],
        **extra,
    }


def _chat_spans(exp: InMemorySpanExporter):
    return [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]


async def test_non_stream_span(env: Env, api_key: str, spans: InMemorySpanExporter) -> None:
    async with env.gateway_client(api_key) as c:
        r = await c.post("/v1/chat/completions", json=_body())
    assert r.status_code == 200
    (s,) = _chat_spans(spans)
    a = dict(s.attributes)
    assert a["cache"] == "miss" and a["finish_reason"] == "stop"
    assert "gen_ai.request.model" in a
    assert isinstance(a["gen_ai.usage.input_tokens"], int)
    assert isinstance(a["gen_ai.usage.output_tokens"], int)
    assert CANARY not in s.to_json()


async def test_stream_span_ends_with_finish_reason(
    env: Env, api_key: str, spans: InMemorySpanExporter
) -> None:
    async with env.gateway_client(api_key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json=_body(stream=True, stream_options={"include_usage": True}),
        )
        assert r.status_code == 200
        _ = r.text
    (s,) = _chat_spans(spans)
    assert s.attributes["finish_reason"] == "stop"
    assert "gen_ai.usage.output_tokens" in s.attributes
    assert CANARY not in s.to_json()
