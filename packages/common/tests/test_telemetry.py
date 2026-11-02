"""Telemetry: allowlist thuộc tính, bỏ message exception, trace_id trong log, tắt khi không có endpoint."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from acme_common import telemetry
from acme_common.log import JsonFormatter
from acme_common.metrics import HttpMetrics, HttpMetricsMiddleware, bearer_ok
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry, generate_latest

CANARY = "CANARY-9f3a"


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(telemetry.AllowlistSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exp))
    return exp, provider.get_tracer("t")


def test_attribute_ngoai_allowlist_bi_bo(exporter) -> None:
    exp, tracer = exporter
    with tracer.start_as_current_span("retrieval") as sp:
        sp.set_attribute("returned", 3)
        sp.set_attribute("prompt", CANARY)
        sp.set_attribute("url.full", f"http://x/?q={CANARY}")
    (s,) = exp.get_finished_spans()
    assert dict(s.attributes) == {"returned": 3}


def test_exception_chi_giu_kieu_khong_giu_message(exporter) -> None:
    exp, tracer = exporter
    with pytest.raises(ValueError), tracer.start_as_current_span("x"):
        raise ValueError(CANARY)
    (s,) = exp.get_finished_spans()
    assert CANARY not in s.to_json()
    assert [dict(e.attributes) for e in s.events] == [{"exception.type": "ValueError"}]
    assert s.status.description is None


def test_log_co_trace_id_khi_co_span(exporter) -> None:
    _, tracer = exporter
    rec = logging.LogRecord("l", logging.INFO, __file__, 1, "m", (), None)
    assert "trace_id" not in json.loads(JsonFormatter("svc").format(rec))
    with tracer.start_as_current_span("s") as sp:
        out = json.loads(JsonFormatter("svc").format(rec))
        assert out["trace_id"] == format(sp.get_span_context().trace_id, "032x")


def test_setup_khong_lam_gi_khi_endpoint_trong(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    assert telemetry.setup_telemetry("svc") is False
    app = object()
    assert telemetry.traced_asgi(app, "svc") is app


async def test_inject_trace_headers_gan_traceparent(exporter) -> None:
    from opentelemetry import context, trace

    _, tracer = exporter
    req = SimpleNamespace(headers={})
    span = tracer.start_span("s")
    token = context.attach(trace.set_span_in_context(span))
    try:
        await telemetry.inject_trace_headers(req)
    finally:
        context.detach(token)
        span.end()
    assert req.headers["traceparent"].startswith("00-")


def test_bearer_ok() -> None:
    assert bearer_ok("Bearer abc", "abc")
    assert not bearer_ok("Bearer x", "abc")
    assert not bearer_ok("", None)


async def test_http_metrics_middleware_dung_mau_route() -> None:
    reg = CollectorRegistry()
    m = HttpMetrics(reg, "t")

    async def app(scope, receive, send) -> None:
        scope["route"] = SimpleNamespace(path="/runs/{id}")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def noop(_):
        return None

    await HttpMetricsMiddleware(app, metrics=m)({"type": "http"}, None, noop)
    text = generate_latest(reg).decode()
    assert 't_http_requests_total{route="/runs/{id}",status="200"} 1.0' in text
