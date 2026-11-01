"""Lỗi trung lập ở biên các port của tickets-mcp. Message không chứa dữ liệu người dùng/secret."""

from __future__ import annotations

from acme_common.ports.errors import NotConfigured


class TicketRepositoryNotConfigured(NotConfigured):
    pass


class IntentIssuerNotConfigured(NotConfigured):
    pass


class ApprovalVerifierNotConfigured(NotConfigured):
    pass


class ReplayGuardNotConfigured(NotConfigured):
    pass


class TicketConflict(Exception):
    """`expected_updated_at` lệch (ticket đã đổi sau khi duyệt) hoặc ticket đã ở trạng thái cuối."""


class DuplicateIntent(Exception):
    """Vi phạm UNIQUE(intent_id) hoặc UNIQUE(approval_jti): intent này đã được áp dụng."""


class RepositoryRolledBack(Exception):
    """Transaction chắc chắn đã rollback (không có tác dụng phụ). Intent có thể chuyển `failed`."""


class RepositoryUnavailable(Exception):
    """Kết quả không xác định (vd mất kết nối lúc COMMIT) hoặc không kết nối được."""

    def __init__(self, kind: str = "unavailable", *, retryable: bool = True) -> None:
        super().__init__(f"repository_unavailable: {kind}")
        self.kind = kind
        self.retryable = retryable


class UnsupportedOperation(Exception):
    """Repository không hỗ trợ `op` này."""


class BackendUnavailable(Exception):
    """Kho trạng thái (Redis) không phản hồi: fail-closed (`upstream_unavailable`)."""


class IntentInvalid(Exception):
    """Intent đã lưu có chữ ký sai/hash lệch/định dạng hỏng: coi như bị giả mạo (`intent_mismatch`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"intent_invalid: {reason}")
        self.reason = reason


class ApprovalRejected(Exception):
    """Approval token không đạt; `code` là mã lỗi tool (`approval_*`)."""

    def __init__(self, code: str, reason: str = "") -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
