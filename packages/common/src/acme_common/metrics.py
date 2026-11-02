"""Metric Prometheus dùng chung cho service ngoài gateway (agent, docs-mcp).

Quy tắc nhãn: chỉ giá trị hữu hạn (mẫu route, mode, kết quả). KHÔNG nhãn theo user, thread,
câu hỏi hay nội dung (cache-observability.md §3).
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

CONTENT_TYPE = "text/plain; version=0.0.4"
_UNMATCHED = "unmatched"


def metrics_body(registry: CollectorRegistry) -> bytes:
    return generate_latest(registry)


def bearer_ok(authorization: str, token: str | None) -> bool:
    """`/metrics` yêu cầu bearer METRICS_TOKEN (contracts §1); chưa cấu hình token thì từ chối."""
    got = authorization.removeprefix("Bearer ").strip()
    return bool(token) and hmac.compare_digest(got.encode(), (token or "").encode())


class HttpMetrics:
    """Đếm và đo thời gian request HTTP theo mẫu route; middleware ASGI thuần (không đệm SSE)."""

    def __init__(self, registry: CollectorRegistry, prefix: str) -> None:
        self.requests = Counter(
            f"{prefix}_http_requests_total",
            "Request HTTP theo mẫu route và status",
            ["route", "status"],
            registry=registry,
        )
        self.duration = Histogram(
            f"{prefix}_http_request_duration_seconds",
            "Thời gian xử lý request HTTP (đến khi gửi xong body)",
            ["route"],
            registry=registry,
        )

    def record(self, route: str, status: int, seconds: float) -> None:
        if route in ("/healthz", "/metrics"):
            return
        self.requests.labels(route, str(status)).inc()
        self.duration.labels(route).observe(seconds)


class HttpMetricsMiddleware:
    """Middleware ASGI thuần (không đệm SSE); dùng `app.add_middleware(HttpMetricsMiddleware, metrics=m)`."""

    def __init__(self, app: Any, metrics: HttpMetrics) -> None:
        self._app = app
        self._metrics = metrics

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        status = 500
        start = time.perf_counter()

        async def send_wrapper(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            route = getattr(scope.get("route"), "path", None) or _UNMATCHED
            self._metrics.record(route, status, time.perf_counter() - start)
