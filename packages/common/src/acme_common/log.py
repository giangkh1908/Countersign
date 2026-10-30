"""Logging JSON có cấu trúc (module thường, không phải port).

- Mỗi dòng là một object JSON: `ts`, `level`, `logger`, `msg`, `service`, `request_id`, cùng các
  trường truyền qua `extra={"fields": {...}}`.
- `request_id` lấy từ contextvar (`bind_request_id`), không cần truyền tay.
- Không log payload: khoá nhạy cảm (token, authorization, password, secret, body...) bị che.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "acme_request_id", default=None
)

_REDACT_EXACT = frozenset(
    {
        "token",
        "authorization",
        "password",
        "secret",
        "api_key",
        "apikey",
        "cookie",
        "set-cookie",
        "payload",
        "body",
        "prompt",
        "content",
        "messages",
    }
)
_REDACT_SUFFIX = ("_token", "_secret", "_password", "_api_key", "_cookie", "_payload", "_body")


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request_id(request_id: str | None = None) -> contextvars.Token[str | None]:
    """Gắn request_id cho ngữ cảnh hiện tại; trả token để `reset_request_id`."""
    return request_id_var.set(request_id or new_request_id())


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    request_id_var.reset(token)


def get_request_id() -> str | None:
    return request_id_var.get()


def _scrub(value: Any, key: str | None = None) -> Any:
    if key is not None:
        k = key.lower()
        if k in _REDACT_EXACT or k.endswith(_REDACT_SUFFIX):
            return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str = "") -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if self._service:
            out["service"] = self._service
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            out.update({k: v for k, v in _scrub(fields).items() if k not in out})
        if record.exc_info and record.exc_info[0] is not None:
            out["exc_type"] = record.exc_info[0].__name__
            out["traceback"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", service: str = "") -> None:
    """Cấu hình root logger xuất JSON ra stderr (gọi một lần lúc khởi động)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
