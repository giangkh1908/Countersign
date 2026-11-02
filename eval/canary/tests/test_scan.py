"""Bộ quét canary: có canary là đỏ, sạch là xanh, đọc đúng cấu trúc trace của Tempo."""

from __future__ import annotations

import base64

from eval.canary.scan import Finding, missing_hops, new_canary, scan_text, summarize_trace


def test_canary_ngau_nhien_va_khac_nhau() -> None:
    a, b = new_canary(), new_canary()
    assert a != b and len(a) >= 16


def test_scan_thay_nguyen_van_chu_thuong_va_base64() -> None:
    c = new_canary()
    assert scan_text("x", f"msg={c}", c) == Finding("x", 1)
    assert scan_text("x", c.lower(), c) is not None
    assert scan_text("x", base64.b64encode(c.encode()).decode(), c) is not None


def test_scan_sach_la_none() -> None:
    assert scan_text("x", "không có gì ở đây", new_canary()) is None


def _doc(key: str) -> dict:
    span = {"name": "POST /api/chat"}
    rs = [
        {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "bff"}}]},
            "scopeSpans": [{"spans": [span, span]}],
        },
        {
            "resource": {
                "attributes": [{"key": "service.name", "value": {"stringValue": "agent"}}]
            },
            "scopeSpans": [{"spans": [span]}],
        },
    ]
    return {"trace": {key: rs}} if key == "resourceSpans" else {key: rs}


def test_tom_tat_trace_ca_hai_dang_tempo() -> None:
    for key in ("batches", "resourceSpans"):
        s = summarize_trace(_doc(key))
        assert s.spans == 3 and s.services == {"bff", "agent"}


def test_thieu_hop() -> None:
    s = summarize_trace(_doc("batches"))
    assert missing_hops(s, ("bff", "agent", "gateway", "docs-mcp")) == ["gateway", "docs-mcp"]
