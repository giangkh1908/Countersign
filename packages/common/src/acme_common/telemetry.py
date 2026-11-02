"""Trace OpenTelemetry dùng chung (cache-observability.md §2).

- `setup_telemetry(service)` không làm gì khi `OTEL_EXPORTER_OTLP_ENDPOINT` trống: stack mặc định
  không tốn thêm tài nguyên và không đổi hành vi.
- Trace KHÔNG được chứa nội dung (prompt, tài liệu, câu trả lời). Bảo đảm ở MỘT chỗ:
  `AllowlistSpanProcessor` bỏ mọi thuộc tính span ngoài `ALLOWED_ATTRIBUTES`, bỏ mọi event
  trừ `exception` (chỉ giữ `exception.type`), và bỏ mô tả của status (SDK ghi kèm message lỗi).
  Quên đặt tên thuộc tính ở một span thì thuộc tính đó bị bỏ, không rò.
- Client MCP của agent dùng `httpx2`, instrumentation của `httpx` không áp dụng được: dùng
  `inject_trace_headers` làm event hook `request`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import SpanProcessor

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan, Span

log = logging.getLogger(__name__)

# Danh sách DUY NHẤT các thuộc tính span được xuất. Chỉ số đếm, nhãn hữu hạn, mã trạng thái.
# Cố ý KHÔNG có: url.full, url.path, url.query, http.target, http.url, user_agent.*, client.*,
# enduser.*, db.statement, mọi thứ mang nội dung hay định danh người dùng.
ALLOWED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # HTTP (semconv cũ và mới); route là mẫu đường dẫn, không phải đường dẫn thật
        "http.request.method",
        "http.response.status_code",
        "http.method",
        "http.status_code",
        "http.route",
        "http.scheme",
        "url.scheme",
        "server.address",
        "server.port",
        "network.protocol.version",
        "net.host.name",
        "net.host.port",
        "net.peer.name",
        "net.peer.port",
        "error.type",
        # truy xuất / kiểm chứng
        "candidates",
        "returned",
        "reranked",
        "mode",
        "claims",
        "verified",
        "failed",
        # gateway LLM
        "gen_ai.request.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "cache",
        "finish_reason",
        # tool
        "tool",
        "outcome",
    }
)

_ALLOWED_EVENT = "exception"
_ALLOWED_EVENT_ATTRS = frozenset({"exception.type"})


def _sanitize_attributes(attrs: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (attrs or {}).items() if k in ALLOWED_ATTRIBUTES}


class AllowlistSpanProcessor(SpanProcessor):
    """SpanProcessor đặt TRƯỚC bộ xuất: làm sạch span ở `on_end` rồi mới đến exporter."""

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        from opentelemetry.sdk.trace import Event
        from opentelemetry.trace import Status

        s: Any = span  # chạm trường nội bộ của SDK: bản đã `end()` không còn bị ghi nữa
        s._attributes = _sanitize_attributes(span.attributes)
        s._events = [
            Event(
                e.name,
                {k: v for k, v in (e.attributes or {}).items() if k in _ALLOWED_EVENT_ATTRS},
                e.timestamp,
            )
            for e in span.events
            if e.name == _ALLOWED_EVENT
        ]
        s._links = []
        s._status = Status(span.status.status_code)  # bỏ description (có thể chứa message lỗi)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


_lock = threading.Lock()
_configured = False


def telemetry_enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def setup_telemetry(service_name: str) -> bool:
    """Dựng TracerProvider + OTLP/HTTP exporter + instrumentation `httpx`. Trả True nếu đã bật."""
    global _configured
    if not telemetry_enabled():
        return False
    with _lock:
        if _configured:
            return True
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(AllowlistSpanProcessor())  # trước exporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        _configured = True
        log.info("telemetry_enabled", extra={"fields": {"service": service_name}})
        return True


_EXCLUDED_URLS = "healthz,metrics"


def instrument_fastapi(app: Any, service_name: str) -> None:
    """Bật trace cho app FastAPI (không làm gì khi telemetry tắt)."""
    if not setup_telemetry(service_name):
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app, excluded_urls=_EXCLUDED_URLS, exclude_spans=["receive", "send"]
    )


def traced_asgi(app: Any, service_name: str) -> Any:
    """Bọc app ASGI thuần (vd docs-mcp) bằng middleware trace; telemetry tắt thì trả nguyên app."""
    if not setup_telemetry(service_name):
        return app
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

    return OpenTelemetryMiddleware(
        app, excluded_urls=_EXCLUDED_URLS, exclude_spans=["receive", "send"]
    )


async def inject_trace_headers(request: Any) -> None:
    """Event hook `request` cho client httpx2: gắn `traceparent` từ span hiện tại.

    Không có span hợp lệ (telemetry tắt) thì `inject` không ghi gì.
    """
    propagate.inject(request.headers)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Span thủ công. Thuộc tính ngoài allowlist bị bỏ ở bộ xử lý; exception không ghi message."""
    tracer = trace.get_tracer("acme")
    with tracer.start_as_current_span(
        name, attributes=attributes, record_exception=False, set_status_on_exception=False
    ) as sp:
        try:
            yield sp
        except Exception as e:
            sp.set_attribute("error.type", type(e).__name__)
            raise


def start_span(name: str, **attributes: Any) -> Any:
    """Span KHÔNG đặt làm span hiện tại, cho luồng sống qua `yield` (SSE) hoặc ngoài `with`.

    Cha là span hiện tại lúc gọi. Người gọi phải `end()`. Thuộc tính ngoài allowlist bị bỏ ở bộ xử lý.
    """
    return trace.get_tracer("acme").start_span(
        name, attributes=attributes, record_exception=False, set_status_on_exception=False
    )


def current_trace_id() -> str | None:
    """trace_id (32 hex) của span hiện tại, None nếu không có span hợp lệ."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
