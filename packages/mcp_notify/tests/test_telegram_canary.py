"""Adapter Telegram: các nhánh lỗi, và canary: token giả không lọt vào log, exception, span.

Dùng server HTTP cục bộ (transport httpx thật, để instrumentation OTel toàn cục có cơ hội bọc) thay vì
gọi api.telegram.org.
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from acme_common.telemetry import AllowlistSpanProcessor
from mcp_notify.adapters.telegram import TelegramMessageChannel
from mcp_notify.ports import ChannelSendError
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

TOKEN = "123456:CANARY-SECRET-TOKEN"
CHAT = "-1009876543"


class _Server:
    """Máy chủ giả: trả theo `plan` (status, body, delay_s) cho từng request."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.plan: tuple[int, object] = (200, {"ok": True, "result": {"message_id": 7}})
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("content-length", 0))
                outer.requests.append({"path": self.path, "body": json.loads(self.rfile.read(n))})
                status, body = outer.plan
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a) -> None:  # noqa: D401
                return

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def spans():
    """OTel thật: instrument toàn cục httpx + AllowlistSpanProcessor, như acme_common.telemetry."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AllowlistSpanProcessor())  # trước exporter
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    try:
        yield exporter
    finally:
        HTTPXClientInstrumentor().uninstrument()
        trace._TRACER_PROVIDER = None  # noqa: SLF001


def mk(server: _Server, **kw) -> TelegramMessageChannel:
    return TelegramMessageChannel(
        TOKEN, lambda ref: CHAT if ref == "REF" else None, api_base=server.base, **kw
    )


# ---------------------------------------------------------------- nhánh thành công và lỗi
async def test_send_ok(server) -> None:
    ch = mk(server)
    r = await ch.send("REF", "xin chào")
    await ch.aclose()
    assert r.message_ref == "7"
    req = server.requests[0]
    assert req["path"] == f"/bot{TOKEN}/sendMessage"
    assert req["body"] == {
        "chat_id": CHAT,
        "text": "xin chào",
        "link_preview_options": {"is_disabled": True},
    }  # không parse_mode


async def test_unresolved_chat_ref(server) -> None:
    ch = mk(server)
    with pytest.raises(ChannelSendError) as e:
        await ch.send("OTHER", "x")
    assert e.value.kind == "not_configured" and e.value.delivered == "no" and not server.requests
    await ch.aclose()


CASES = [
    (200, {"ok": False}, "bad_response", None, "unknown"),
    (200, b"not json", "bad_response", None, "unknown"),
    (200, {"ok": False, "error_code": 400}, "http_4xx", 200, "no"),
    (400, {"ok": False, "error_code": 400}, "http_4xx", 400, "no"),
    (403, {"ok": False, "error_code": 403}, "http_4xx", 403, "no"),
    (404, b"", "http_4xx", 404, "no"),
    (429, {"ok": False, "parameters": {"retry_after": 3}}, "rate_limited", 429, "no"),
    (500, {"ok": False}, "http_5xx", 500, "unknown"),
    (502, b"<html>", "http_5xx", 502, "unknown"),
    (302, b"", "bad_response", 302, "unknown"),
]


@pytest.mark.parametrize(("status", "body", "kind", "st", "delivered"), CASES)
async def test_error_mapping(server, status, body, kind, st, delivered) -> None:
    server.plan = (status, body)
    ch = mk(server)
    with pytest.raises(ChannelSendError) as e:
        await ch.send("REF", "x")
    await ch.aclose()
    err = e.value
    assert err.kind == kind and err.delivered == delivered
    if kind == "rate_limited":
        assert err.retry_after_s == 3.0 and err.safe_to_retry
    if kind in ("http_4xx", "bad_response", "http_5xx"):
        assert not err.safe_to_retry


def test_empty_token_refused() -> None:
    with pytest.raises(ValueError):
        TelegramMessageChannel("", lambda r: CHAT)


def test_repr_hides_token() -> None:
    ch = TelegramMessageChannel(TOKEN, lambda r: CHAT)
    assert TOKEN not in repr(ch) and TOKEN not in str(ch)


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("exc", "kind", "delivered"),
    [
        (httpx.ConnectError, "connect", "no"),
        (httpx.ConnectTimeout, "connect", "no"),
        (httpx.PoolTimeout, "connect", "no"),
        (httpx.ReadTimeout, "timeout", "unknown"),
        (httpx.WriteTimeout, "timeout", "unknown"),
        (httpx.ReadError, "transport", "unknown"),
        (httpx.RemoteProtocolError, "transport", "unknown"),
        (RuntimeError, "internal", "unknown"),
    ],
)
async def test_transport_exceptions_map_without_leaking(exc, kind, delivered) -> None:
    def boom(request: httpx.Request):
        raise exc(f"fail {request.url}")  # message chứa URL có token, phải bị chặn lại

    ch = TelegramMessageChannel(TOKEN, lambda r: CHAT, transport=_mock(boom))
    with pytest.raises(ChannelSendError) as e:
        await ch.send("REF", "x")
    err = e.value
    assert err.kind == kind and err.delivered == delivered
    assert err.__cause__ is None and err.__context__ is None
    text = "".join(traceback.format_exception(err)) + str(err) + repr(err) + repr(err.args)
    assert TOKEN not in text and "CANARY" not in text
    await ch.aclose()


# ---------------------------------------------------------------- canary: log
async def test_canary_not_in_logs(server, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    for lg in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11"):
        logging.getLogger(lg).setLevel(logging.DEBUG)
    ch = mk(server)
    for plan in [
        (200, {"ok": True, "result": {"message_id": 1}}),
        (429, {"ok": False, "parameters": {"retry_after": 1}}),
        (403, {"ok": False}),
        (500, b"boom"),
    ]:
        server.plan = plan
        try:
            await ch.send("REF", "x")
        except ChannelSendError as e:
            logging.getLogger("acme.test").warning("lỗi gửi: %s %r", e, e)
    await ch.aclose()
    assert TOKEN not in caplog.text and "CANARY" not in caplog.text
    assert "/sendMessage" not in "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith("http")
    )


# ---------------------------------------------------------------- canary: span
async def test_control_plain_client_is_traced_adapter_is_not(server, spans) -> None:
    # đối chứng: client thường bị instrument toàn cục => span mang URL
    async with httpx.AsyncClient() as plain:
        await plain.post(f"{server.base}/bot{TOKEN}/sendMessage", json={})
    assert len(spans.get_finished_spans()) >= 1
    spans.clear()
    # client của adapter đã gỡ instrumentation => không span nào
    ch = mk(server)
    await ch.send("REF", "x")
    server.plan = (500, b"x")
    with pytest.raises(ChannelSendError):
        await ch.send("REF", "x")
    await ch.aclose()
    assert spans.get_finished_spans() == ()


async def test_canary_not_in_spans_even_for_plain_client_after_allowlist(server, spans) -> None:
    ch = mk(server)
    server.plan = (403, {"ok": False})
    with pytest.raises(ChannelSendError):
        await ch.send("REF", "x")
    await ch.aclose()
    dump = json.dumps(
        [
            {
                "name": s.name,
                "attrs": dict(s.attributes or {}),
                "events": [e.name for e in s.events],
            }
            for s in spans.get_finished_spans()
        ],
        default=str,
    )
    assert TOKEN not in dump and "CANARY" not in dump


async def test_connect_refused_no_leak(caplog, spans) -> None:
    caplog.set_level(logging.DEBUG)
    ch = TelegramMessageChannel(
        TOKEN,
        lambda r: CHAT,
        api_base="http://127.0.0.1:1",  # không ai nghe
    )
    with pytest.raises(ChannelSendError) as e:
        await ch.send("REF", "x")
    await ch.aclose()
    assert e.value.kind == "connect" and e.value.safe_to_retry
    text = caplog.text + "".join(traceback.format_exception(e.value))
    assert TOKEN not in text and "CANARY" not in text
    assert spans.get_finished_spans() == ()


def test_client_refuses_to_start_if_still_instrumented(monkeypatch) -> None:
    monkeypatch.setattr(
        HTTPXClientInstrumentor, "uninstrument_client", staticmethod(lambda c: None)
    )

    class Wrapped(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):  # pragma: no cover
            raise AssertionError

    t = Wrapped()

    def wrapper(*a, **k):  # pragma: no cover
        return None

    wrapper.__wrapped__ = Wrapped.handle_async_request  # type: ignore[attr-defined]
    t.handle_async_request = wrapper  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        TelegramMessageChannel(TOKEN, lambda r: CHAT, transport=t)
