"""Adapter `mcp_http` của `ToolProvider`: MCP client Streamable HTTP (SDK `mcp`), file duy nhất import `mcp`.

- Khám phá tool động bằng `list_tools`, lọc theo allowlist của agent (`AgentAccess`).
- Mỗi lời gọi lấy token đã exchange đúng audience của server (`TokenBroker`), đặt `Bearer`.
- `thread_id` truyền qua `_meta["io.acme/thread_id"]` trong mọi lời gọi.
- `commit_intent` chỉ gửi `{intent_id, approval_token}`, một lần, không retry.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx2
from acme_common.mcp.context import THREAD_ID_META_KEY
from acme_common.ports import Principal, TokenBroker
from acme_common.telemetry import inject_trace_headers
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from ..ports.errors import ToolUnavailable
from ..ports.tool_provider import AgentAccess, ServerAccess, ToolProvider

HttpClientFactory = Callable[[dict[str, str]], httpx2.AsyncClient]
_DISCOVERY_TTL_S = 300.0
MAX_OUTPUT_BYTES = 8192
# Tool `prepare_*` mang intent_jws (chữ ký) nên cắt là hỏng chữ ký; chỉ các tool này được miễn.
_NO_TRUNCATE = frozenset({"prepare_close_ticket", "prepare_create_ticket"})


def _default_http(headers: dict[str, str]) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        headers=headers,
        timeout=httpx2.Timeout(30.0, read=60.0),
        event_hooks={
            "request": [inject_trace_headers]
        },  # traceparent sang MCP (httpx2 không có instrumentation)
    )


class McpHttpToolProvider(ToolProvider):
    def __init__(
        self,
        servers: Mapping[str, str],
        broker: TokenBroker,
        access: Mapping[str, AgentAccess],
        *,
        write_broker: TokenBroker | None = None,
        http_client_factory: HttpClientFactory = _default_http,
    ) -> None:
        self._servers = dict(servers)
        self._broker = broker
        self._write_broker = write_broker or broker  # token tickets:write không cache
        self._access = dict(access)
        self._http = http_client_factory
        self._discovered: dict[str, tuple[float, list[Any]]] = {}

    # --- hạ tầng MCP ---
    def _broker_for(self, sa: ServerAccess) -> TokenBroker:
        return self._broker if sa.cache_token else self._write_broker

    async def _token(self, sa: ServerAccess, principal: Principal, user_token: str) -> str:
        tok = await self._broker_for(sa).token_for(principal, user_token, sa.audience, sa.scopes)
        return tok.value

    def _url(self, audience: str) -> str:
        try:
            return self._servers[audience]
        except KeyError:
            raise ToolUnavailable(audience) from None

    async def _call_raw(
        self,
        sa: ServerAccess,
        name: str,
        args: dict[str, Any],
        principal: Principal,
        user_token: str,
        thread_id: str | None,
    ) -> tuple[bool, Any]:
        token = await self._token(sa, principal, user_token)
        meta = {THREAD_ID_META_KEY: thread_id} if thread_id else None
        try:
            async with (
                self._http({"Authorization": f"Bearer {token}"}) as hc,
                Client(streamable_http_client(self._url(sa.audience), http_client=hc)) as client,
            ):
                res = await client.call_tool(name, args, meta=meta)  # type: ignore[arg-type]
        except ToolUnavailable:
            raise
        except Exception:
            raise ToolUnavailable(sa.audience, retryable=True) from None
        data = res.structured_content
        if data is None:
            text = "".join(getattr(b, "text", "") for b in res.content)
            try:
                data = json.loads(text)
            except ValueError:
                data = {"text": text}
        return bool(res.is_error), data

    async def _discover(self, sa: ServerAccess, principal: Principal, user_token: str) -> list[Any]:
        cached = self._discovered.get(sa.audience)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        token = await self._token(sa, principal, user_token)
        try:
            async with (
                self._http({"Authorization": f"Bearer {token}"}) as hc,
                Client(streamable_http_client(self._url(sa.audience), http_client=hc)) as client,
            ):
                tools = list((await client.list_tools()).tools)
        except ToolUnavailable:
            raise
        except Exception:
            raise ToolUnavailable(sa.audience, retryable=True) from None
        self._discovered[sa.audience] = (time.monotonic() + _DISCOVERY_TTL_S, tools)
        return tools

    # --- port ---
    async def tools_for(
        self,
        agent_name: str,
        principal: Principal,
        user_token: str,
        *,
        thread_id: str | None = None,
    ) -> list[BaseTool]:
        access = self._access.get(agent_name)
        if access is None:
            return []
        out: list[BaseTool] = []
        groups = list(access.read) + ([access.prepare] if access.prepare else [])
        for sa in groups:
            for t in await self._discover(sa, principal, user_token):
                if t.name in sa.tools:
                    out.append(self._wrap(sa, t, principal, user_token, thread_id))
        return out

    def _wrap(
        self,
        sa: ServerAccess,
        tool_def: Any,
        principal: Principal,
        user_token: str,
        thread_id: str | None,
    ) -> BaseTool:
        name = tool_def.name

        async def _run(**kwargs: Any) -> str:
            is_error, data = await self._call_raw(
                sa, name, kwargs, principal, user_token, thread_id
            )
            text = json.dumps(data, ensure_ascii=False)
            if is_error:
                raise ToolException(text)
            if len(text.encode()) > MAX_OUTPUT_BYTES and name not in _NO_TRUNCATE:
                text = text.encode()[:MAX_OUTPUT_BYTES].decode(errors="ignore") + " [...cắt]"
            return text

        return StructuredTool(
            name=name,
            description=tool_def.description or name,
            args_schema=dict(tool_def.input_schema),
            coroutine=_run,
        )

    async def commit_intent(
        self,
        agent_name: str,
        intent_id: str,
        approval_token: str,
        *,
        principal: Principal,
        user_token: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        access = self._access.get(agent_name)
        if access is None or access.commit is None:
            raise ToolUnavailable(agent_name)
        is_error, data = await self._call_raw(
            access.commit,
            "commit_intent",
            {"intent_id": intent_id, "approval_token": approval_token},
            principal,
            user_token,
            thread_id,
        )
        if not is_error:
            return {"ok": True, **(data if isinstance(data, dict) else {})}
        err = data.get("error", {}) if isinstance(data, dict) else {}
        return {
            "ok": False,
            "error": {
                "code": str(err.get("code", "internal_error")),
                "message": str(err.get("message", "")),
                "details": err.get("details", {}),
            },
        }
