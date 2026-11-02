"""Lỗi trung lập ở biên các port của tickets-mcp. Message không chứa dữ liệu người dùng/secret.

Lỗi thực thi kế thừa lỗi chung của `acme_common` để `IntentCommitService` bắt được mà không biết ticket.
"""

from __future__ import annotations

from acme_common.ports import ExecutionConflict, ExecutionRolledBack, ExecutionUnavailable
from acme_common.ports.errors import NotConfigured


class TicketRepositoryNotConfigured(NotConfigured):
    pass


class TicketConflict(ExecutionConflict):
    """`expected_updated_at` lệch (ticket đã đổi sau khi duyệt) hoặc ticket đã ở trạng thái cuối."""


class RepositoryRolledBack(ExecutionRolledBack):
    """Transaction chắc chắn đã rollback (không có tác dụng phụ). Intent có thể chuyển `failed`."""


class RepositoryUnavailable(ExecutionUnavailable):
    """Kết quả không xác định (vd mất kết nối lúc COMMIT) hoặc không kết nối được."""

    def __init__(self, kind: str = "unavailable", *, retryable: bool = True) -> None:
        super().__init__(f"repository_unavailable: {kind}")
        self.kind = kind
        self.retryable = retryable


class UnsupportedOperation(Exception):
    """Repository không hỗ trợ `op` này."""
