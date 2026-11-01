"""Port `ToolProvider` (contracts §9.2): nạp tool theo agent và commit intent đã được duyệt.

Adapter v1: `mcp_http` (adapters/). Test: `FakeToolProvider` (agent.testing).
`commit_intent` KHÔNG nằm trong danh sách tool trả cho LLM; chỉ node `execute_write` gọi.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from acme_common.ports import Principal
from langchain_core.tools import BaseTool


@dataclass(frozen=True, slots=True)
class ServerAccess:
    """Quyền của một agent trên một MCP server: audience, tool được phép (allowlist), scope xin."""

    audience: str
    tools: frozenset[str]
    scopes: tuple[str, ...]
    cache_token: bool = True  # token tickets:write không cache


@dataclass(frozen=True, slots=True)
class AgentAccess:
    """Allowlist của một agent (lấy từ `AgentSpec`)."""

    read: tuple[ServerAccess, ...] = ()
    prepare: ServerAccess | None = None  # các `prepare_*` (nạp cho LLM, không đổi dữ liệu)
    commit: ServerAccess | None = None  # server + scope cho `commit_intent` (không nạp cho LLM)


class ToolProvider(abc.ABC):
    @abc.abstractmethod
    async def tools_for(
        self,
        agent_name: str,
        principal: Principal,
        user_token: str,
        *,
        thread_id: str | None = None,
    ) -> list[BaseTool]:
        """Tool của agent (đọc + `prepare_*`), đã lọc allowlist. Mỗi lời gọi tool mang `thread_id`
        trong `_meta`. Tool trả chuỗi JSON của `structuredContent`; lỗi nghiệp vụ => `ToolException`.

        Raise `ToolUnavailable`, `TokenExchangeDenied`.
        """

    @abc.abstractmethod
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
        """Gọi `commit_intent(intent_id, approval_token)` một lần, không retry.

        Trả `{"ok": True, ...}` hoặc `{"ok": False, "error": {"code", "message", "details"}}`
        (lỗi nghiệp vụ). Raise `ToolUnavailable` khi lỗi truyền tải.
        """
