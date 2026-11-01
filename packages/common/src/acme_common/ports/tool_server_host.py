"""Port `ToolServerHost` (contracts §9.2): `register(spec, handler)`, `asgi_app()`.

Host chỉ lo giao thức MCP (Streamable HTTP, stateless). KHÔNG làm auth (ADR-003): `AuthMiddleware`
bọc ngoài `asgi_app()`. `handler` ở mức port là `RawToolHandler` (đã gồm validate/scope/rate limit/
timeout/audit do `ToolInvoker.wrap` bọc); host không tự validate lần nữa.
Adapter v1: `mcp_sdk` (mặc định, ADR-003). Milestone M1.
"""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ASGIApp = Callable[..., Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Khai báo một tool (02 §1.1). `description`/`input_schema` là nguồn của digest pinning."""

    name: str
    description: str
    input_schema: Mapping[str, Any]  # JSON Schema 2020-12, additionalProperties:false
    title: str | None = None
    output_schema: Mapping[str, Any] | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)  # readOnlyHint, ...
    required_scopes: tuple[str, ...] = ()
    cost: int = 1  # trọng số rate limit
    timeout_s: float = 10.0
    max_output_bytes: int = 32_768
    requires_approval: bool = False
    timeout_code: str = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Kết quả trung lập của một lời gọi tool. Lỗi: `is_error=True`, `data` = `{code, message, ...}`."""

    data: Mapping[str, Any]
    is_error: bool = False


# (arguments, meta) -> kết quả. `meta` là `_meta` của request MCP (có thể rỗng).
RawToolHandler = Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[ToolResult]]


class ToolServerHost(abc.ABC):
    @abc.abstractmethod
    def register(self, spec: ToolSpec, handler: RawToolHandler) -> None:
        """Đăng ký tool. Tên trùng => `ValueError`."""

    @abc.abstractmethod
    def asgi_app(self) -> ASGIApp:
        """ASGI app xử lý `POST /mcp`; không tự xác thực."""

    @abc.abstractmethod
    def tool_manifest(self) -> list[dict[str, Any]]:
        """Danh sách tool đã đăng ký dạng dict (name, description, inputSchema, ...)."""
