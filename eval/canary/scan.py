"""Quét canary: hàm thuần, không I/O (cache-observability.md §4).

Canary là chuỗi ngẫu nhiên gửi trong câu hỏi. Nội dung người dùng không được xuất hiện trong log
hay trace; thấy canary ở đó là rò rỉ. Mỗi nơi quét cho ra `Finding`, có Finding là đỏ.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from typing import Any


def new_canary() -> str:
    """Chuỗi ngẫu nhiên, không đoán trước được, không trùng nội dung thật."""
    return "CNRY" + secrets.token_hex(10)


def variants(canary: str) -> tuple[str, ...]:
    """Dạng gặp trong log/trace: nguyên văn, chữ thường, base64 của nguyên văn."""
    b64 = base64.b64encode(canary.encode()).decode().rstrip("=")
    return (canary, canary.lower(), b64[:-2] if len(b64) > 8 else b64)


@dataclass(frozen=True)
class Finding:
    where: str
    count: int


def scan_text(where: str, text: str, canary: str) -> Finding | None:
    n = sum(text.count(v) for v in variants(canary))
    return Finding(where, n) if n else None


@dataclass
class TraceSummary:
    spans: int = 0
    services: set[str] = field(default_factory=set)
    span_names: list[str] = field(default_factory=list)


def _resource_spans(doc: dict[str, Any]) -> list[dict[str, Any]]:
    # Tempo trả `batches` (v1) hoặc `resourceSpans` / `trace.resourceSpans` (v2), tuỳ phiên bản
    for node in (doc, doc.get("trace") or {}):
        for key in ("batches", "resourceSpans"):
            if node.get(key):
                return list(node[key])
    return []


def summarize_trace(doc: dict[str, Any]) -> TraceSummary:
    out = TraceSummary()
    for rs in _resource_spans(doc):
        service = ""
        for attr in (rs.get("resource") or {}).get("attributes", []):
            if attr.get("key") == "service.name":
                service = str((attr.get("value") or {}).get("stringValue", ""))
        scopes = rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []
        for scope in scopes:
            for sp in scope.get("spans", []):
                out.spans += 1
                out.services.add(service)
                out.span_names.append(f"{service}:{sp.get('name', '')}")
    return out


def missing_hops(summary: TraceSummary, required: tuple[str, ...]) -> list[str]:
    return [s for s in required if s not in summary.services]
