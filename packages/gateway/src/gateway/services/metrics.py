"""Metric Prometheus tối thiểu (registry riêng cho mỗi app, dễ test). Chỉ nhãn có tập giá trị hữu hạn."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "gateway_requests_total",
            "Chat requests theo alias và HTTP status",
            ["alias", "status"],
            registry=self.registry,
        )
        self.tokens = Counter(
            "gateway_tokens_total",
            "Token theo hướng input/output",
            ["direction"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "gateway_request_duration_seconds",
            "Thời gian xử lý request chat",
            ["alias"],
            registry=self.registry,
        )
        self.cache_lookups = Counter(
            "gateway_cache_lookups_total",
            "Tra exact cache theo kết quả: hit|miss|bypass|error",
            ["result"],
            registry=self.registry,
        )
        self.cache_stores = Counter(
            "gateway_cache_stores_total",
            "Ghi exact cache theo kết quả: ok|skipped|error",
            ["result"],
            registry=self.registry,
        )
        self.auth_failures = Counter(
            "gateway_auth_failures_total",
            "Xác thực thất bại theo lý do",
            ["reason"],
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)
