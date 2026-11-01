"""Mã lỗi tool MCP chuẩn hoá (contracts §4)."""

from __future__ import annotations

from typing import Any

TOOL_ERROR_CODES = frozenset(
    {
        "unauthorized",
        "forbidden",
        "not_found",
        "invalid_argument",
        "rate_limited",
        "approval_required",
        "approval_invalid",
        "approval_expired",
        "approval_mismatch",
        "approval_replayed",
        "intent_not_found",
        "intent_expired",
        "intent_mismatch",
        "intent_unrenderable",
        "conflict",
        "query_rejected",
        "query_timeout",
        "upstream_unavailable",
        "internal_error",
    }
)
_RETRYABLE = frozenset({"rate_limited", "query_timeout", "upstream_unavailable"})
_DENY = frozenset(
    {
        "unauthorized",
        "forbidden",
        "rate_limited",
        "approval_required",
        "approval_invalid",
        "approval_expired",
        "approval_mismatch",
        "approval_replayed",
    }
)


class ToolError(Exception):
    """Lỗi nghiệp vụ có mã chuẩn. `message` không được chứa dữ liệu người dùng/secret."""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        if code not in TOOL_ERROR_CODES:
            raise ValueError(f"unknown tool error code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message or code
        self.details = details or {}
        self.retryable = code in _RETRYABLE if retryable is None else retryable

    @property
    def decision(self) -> str:
        return "deny" if self.code in _DENY else "error"

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            out["details"] = self.details
        return out
