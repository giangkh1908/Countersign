"""Span `verification`, `tool.{name}` và metric kiểm chứng của agent; không chứa nội dung."""

from __future__ import annotations

import pytest
from acme_common import telemetry
from agent.metrics import REGISTRY
from agent.testing import FakeToolProvider, route, tool_call
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

CANARY = "CANARY-31d8-noi-dung"
SEARCH = {
    "results": [
        {
            "chunk_id": 11,
            "doc_id": "d1",
            "text": f"Xin nghi phep qua HR truoc 3 ngay. {CANARY}",
            "title": "Quy trinh nghi phep",
            "heading": "H",
            "source": "d1#2",
            "classification": "internal",
        }
    ]
}


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(telemetry.AllowlistSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *_a, **_k: provider.get_tracer("t"))
    return exp


def _metric(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_tool_and_verification_spans_and_metric(make_env, spans) -> None:
    before_answers = _metric("agent_answers_total", status="answered")
    before_claims = _metric("agent_claims_total", verdict="supported")
    env = make_env(
        FakeToolProvider({"search_documents": SEARCH}),
        {
            "router": [route("docs")],
            "agent": [
                tool_call("search_documents", {"query": "nghi phep"}),
                AIMessage("Xin nghi phep qua HR truoc 3 ngay [#11]."),
            ],
        },
    )
    tid = await env.new_thread()
    await env.run(tid, f"Quy trinh nghi phep? {CANARY}")
    by_name = {s.name: s for s in spans.get_finished_spans()}
    assert dict(by_name["tool.search_documents"].attributes) == {
        "tool": "search_documents",
        "outcome": "ok",
    }
    v = dict(by_name["verification"].attributes)
    assert v["claims"] >= 1 and v["verified"] >= 1 and v["failed"] == 0
    assert all(CANARY not in s.to_json() for s in spans.get_finished_spans())
    assert _metric("agent_answers_total", status="answered") == before_answers + 1
    assert _metric("agent_claims_total", verdict="supported") > before_claims
