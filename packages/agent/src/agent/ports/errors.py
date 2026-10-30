"""Lỗi trung lập của agent (contracts §9.1 mục 3). Message không chứa token, URL, nội dung người dùng."""

from __future__ import annotations

from acme_common.ports.errors import NotConfigured


class ConfigError(Exception):
    """Cấu hình sai/thiếu: từ chối khởi động."""


class ToolUnavailable(Exception):
    """MCP server không phản hồi hoặc trả lỗi truyền tải. `server` là audience, không phải URL."""

    def __init__(self, server: str, *, retryable: bool = False) -> None:
        super().__init__(f"tool_unavailable: {server}")
        self.server = server
        self.retryable = retryable


class GatewayError(Exception):
    """Lỗi từ LLM gateway đã dịch (03 §5.3). `user_message` là câu tiếng Việt an toàn để hiển thị."""

    def __init__(self, code: str, user_message: str, *, retryable: bool = False) -> None:
        super().__init__(f"gateway_error: {code}")
        self.code = code
        self.user_message = user_message
        self.retryable = retryable


class ToolProviderNotConfigured(NotConfigured):
    pass


class AgentNotConfigured(NotConfigured):
    pass


class ConversationRepoNotConfigured(NotConfigured):
    pass


class CheckpointerNotConfigured(NotConfigured):
    pass


class ServiceProbeNotConfigured(NotConfigured):
    """Tên adapter ServiceProbe lạ."""
