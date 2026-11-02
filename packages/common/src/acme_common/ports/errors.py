"""Lỗi trung lập ở biên các port (contracts §9.1 mục 3).

Message lỗi không bao giờ chứa token, URL, header hay nội dung người dùng; chỉ có mã `reason`
thuộc tập hữu hạn để service ánh xạ sang HTTP (contracts §4).
"""

from __future__ import annotations

# reason -> HTTP status khi một resource server từ chối token (contracts §2, §4).
_TOKEN_REASON_STATUS: dict[str, int] = {
    "malformed": 401,
    "bad_signature": 401,
    "unknown_kid": 401,
    "bad_algorithm": 401,
    "expired": 401,
    "not_yet_valid": 401,
    "bad_issuer": 401,
    "bad_audience": 403,
    "bad_azp": 403,
    "missing_scope": 403,
}


class TokenInvalid(Exception):
    """Token không được chấp nhận. `reason` thuộc `_TOKEN_REASON_STATUS`."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"token_invalid: {reason}")
        self.reason = reason

    @property
    def http_status(self) -> int:
        return _TOKEN_REASON_STATUS.get(self.reason, 401)


class TokenServiceUnavailable(Exception):
    """Không lấy được khoá (JWKS) hoặc IdP không phản hồi; caller trả 503, không phải 401."""

    def __init__(self, component: str) -> None:
        super().__init__(f"token_service_unavailable: {component}")
        self.component = component


class TokenExchangeDenied(Exception):
    """IdP từ chối đổi token, hoặc token đổi ra vi phạm hậu điều kiện ADR-005. Không dùng token đó."""

    def __init__(self, reason: str, *, http_status: int | None = None) -> None:
        super().__init__(f"token_exchange_denied: {reason}")
        self.reason = reason
        self.http_status = http_status


class NotConfigured(ValueError):
    """Gốc của các lỗi `XxxNotConfigured` do factory raise khi tên adapter lạ."""


class ClockNotConfigured(NotConfigured):
    pass


class TokenVerifierNotConfigured(NotConfigured):
    pass


class TokenBrokerNotConfigured(NotConfigured):
    pass


class EventSinkNotConfigured(NotConfigured):
    pass


class RateLimiterNotConfigured(NotConfigured):
    pass


class ToolServerHostNotConfigured(NotConfigured):
    pass


class IntentIssuerNotConfigured(NotConfigured):
    pass


class ApprovalVerifierNotConfigured(NotConfigured):
    pass


class ReplayGuardNotConfigured(NotConfigured):
    pass


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
