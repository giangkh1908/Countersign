"""Ngữ cảnh người gọi: `AuthMiddleware` đặt vào contextvar, `ToolInvoker` đọc ra."""

from __future__ import annotations

import contextvars
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..ports.types import Principal

THREAD_ID_META_KEY = "io.acme/thread_id"
_MAX_THREAD_ID_LEN = 128


@dataclass(frozen=True, slots=True)
class AuthContext:
    principal: Principal
    request_id: str


@dataclass(frozen=True, slots=True)
class CallerContext:
    """Cái handler nghiệp vụ nhận: danh tính đã xác minh + `thread_id` (từ `_meta`, KHÔNG dùng phân quyền)."""

    principal: Principal
    request_id: str
    thread_id: str | None = None


_current: contextvars.ContextVar[AuthContext | None] = contextvars.ContextVar(
    "acme_mcp_auth", default=None
)


def current_auth() -> AuthContext | None:
    return _current.get()


def set_auth(ctx: AuthContext) -> contextvars.Token[AuthContext | None]:
    return _current.set(ctx)


def reset_auth(token: contextvars.Token[AuthContext | None]) -> None:
    _current.reset(token)


def thread_id_from_meta(meta: Mapping[str, Any] | None) -> str | None:
    """`_meta["io.acme/thread_id"]`; giá trị không hợp lệ coi như thiếu (=> dùng khoá `recent`)."""
    if not meta:
        return None
    value = meta.get(THREAD_ID_META_KEY)
    if isinstance(value, str) and 0 < len(value) <= _MAX_THREAD_ID_LEN and value.isprintable():
        return value
    return None
