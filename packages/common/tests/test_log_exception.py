"""Log exception chỉ giữ kiểu và vị trí file:dòng; message (có thể chứa nội dung) không xuất hiện."""

from __future__ import annotations

import json
import logging
import sys

from acme_common.log import JsonFormatter

CANARY = "CANARY-7c41-noi-dung-tai-lieu"


def _boom() -> None:
    raise ValueError(f"khong tim thay: {CANARY}")


def _format_with_exc(chain: bool = False) -> str:
    try:
        try:
            _boom()
        except ValueError as inner:
            if chain:
                raise RuntimeError(f"boc: {CANARY}") from inner
            raise
    except Exception:
        rec = logging.LogRecord(
            "l", logging.ERROR, __file__, 1, "that bai", (), sys.exc_info(), None
        )
        return JsonFormatter("svc").format(rec)
    raise AssertionError("unreachable")


def test_canary_trong_message_exception_khong_vao_log() -> None:
    line = _format_with_exc()
    assert CANARY not in line
    out = json.loads(line)
    assert out["exc_type"] == "ValueError"
    assert "traceback" not in out
    assert any("test_log_exception.py" in f and " in _boom" in f for f in out["exc_at"])
    assert all(f.split(" in ")[0].rsplit(":", 1)[1].isdigit() for f in out["exc_at"])


def test_canary_khong_ro_qua_exception_noi_chuoi() -> None:
    line = _format_with_exc(chain=True)
    assert CANARY not in line
    assert json.loads(line)["exc_type"] == "RuntimeError"
