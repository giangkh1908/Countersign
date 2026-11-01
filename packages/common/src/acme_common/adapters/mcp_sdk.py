"""Adapter `mcp_sdk` cho port `ToolServerHost`: SDK `mcp` 2.3 `MCPServer`, stateless (ADR-003).

SDK chỉ host giao thức. Không dùng validator/auth của SDK: tool được đăng ký với `arg_model` cho
phép mọi tham số (extra=allow) và `parameters` = schema của ta; `ToolInvoker` validate lần thật.
Dùng `Tool`/`ToolManager` nội bộ của SDK (khoá phiên bản `mcp>=2.3,<3`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import ConfigDict

from ..ports.tool_server_host import ASGIApp, RawToolHandler, ToolServerHost, ToolSpec


class _PassthroughArgs(ArgModelBase):
    """Nhận mọi tham số nguyên trạng (không ép kiểu, không loại tham số lạ)."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class McpSdkHost(ToolServerHost):
    def __init__(
        self,
        name: str,
        *,
        streamable_http_path: str = "/mcp",
        allowed_hosts: Sequence[str] = (),
        allowed_origins: Sequence[str] = (),
    ) -> None:
        """`allowed_hosts` (vd `docs-mcp:8101`, `localhost:8101`): chống DNS rebinding của SDK;
        rỗng => mặc định SDK (chỉ loopback)."""
        self._security = (
            TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(allowed_hosts),
                allowed_origins=list(allowed_origins),
            )
            if allowed_hosts
            else None
        )
        self._server = MCPServer(name)
        self._path = streamable_http_path
        self._specs: dict[str, ToolSpec] = {}
        self._app: ASGIApp | None = None

    def register(self, spec: ToolSpec, handler: RawToolHandler) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool {spec.name!r} already registered")

        async def fn(ctx: Any, **arguments: Any) -> CallToolResult:
            meta = getattr(ctx.request_context, "meta", None) or {}
            res = await handler(arguments, dict(meta))
            payload = json.dumps(res.data, ensure_ascii=False)
            return CallToolResult(
                content=[TextContent(type="text", text=payload)],
                structured_content=dict(res.data),
                is_error=res.is_error,
            )

        tool = Tool(
            fn=fn,
            name=spec.name,
            title=spec.title,
            description=spec.description,
            parameters=dict(spec.input_schema),
            fn_metadata=FuncMetadata(
                arg_model=_PassthroughArgs,
                output_schema=dict(spec.output_schema) if spec.output_schema else None,
            ),
            is_async=True,
            context_kwarg="ctx",
            annotations=ToolAnnotations(**dict(spec.annotations)) if spec.annotations else None,
        )
        self._server._tool_manager._tools[spec.name] = tool  # noqa: SLF001 - API SDK không cho schema tuỳ ý
        self._specs[spec.name] = spec

    def asgi_app(self) -> ASGIApp:
        if self._app is None:
            self._app = self._server.streamable_http_app(
                stateless_http=True,
                streamable_http_path=self._path,
                transport_security=self._security,
            )
        return self._app

    def tool_manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "title": s.title,
                "description": s.description,
                "inputSchema": dict(s.input_schema),
                "outputSchema": dict(s.output_schema) if s.output_schema else None,
                "annotations": dict(s.annotations),
            }
            for s in self._specs.values()
        ]
