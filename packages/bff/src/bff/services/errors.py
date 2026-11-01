"""Map lỗi sang JSON chuẩn (contracts §4): `{"error":{"code","message","retryable","request_id"}}`.

Một hàm `to_http_error(exc)` duy nhất. Thông điệp tiếng Việt, chung chung; chi tiết chỉ vào log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from acme_common.http import HttpError
from acme_common.ports import TokenExchangeDenied, TokenInvalid, TokenServiceUnavailable
from redis.exceptions import RedisError

from .crypto import CryptoError

log = logging.getLogger("bff.errors")

_MESSAGES: dict[str, str] = {
    "invalid_request": "Yêu cầu không hợp lệ.",
    "session_expired": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
    "csrf_failed": "Yêu cầu bị từ chối vì không vượt qua kiểm tra CSRF.",
    "forbidden": "Bạn không có quyền thực hiện thao tác này.",
    "not_found": "Không tìm thấy tài nguyên.",
    "interrupt_not_found": "Không tìm thấy yêu cầu phê duyệt. Hãy tải lại cuộc trò chuyện.",
    "conflict": "Thao tác xung đột với trạng thái hiện tại.",
    "intent_expired": "Đề xuất đã hết hạn. Hãy làm mới đề xuất.",
    "request_too_large": "Nội dung yêu cầu quá lớn.",
    "intent_unrenderable": "Không thể hiển thị đầy đủ nội dung cần duyệt nên không cho phép duyệt.",
    "intent_mismatch": "Nội dung duyệt không khớp với đề xuất. Hãy tải lại thẻ duyệt.",
    "rate_limited": "Bạn thao tác quá nhanh. Vui lòng thử lại sau.",
    "upstream_unavailable": "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại.",
    "upstream_timeout": "Dịch vụ phản hồi quá chậm. Vui lòng thử lại.",
    "internal": "Đã xảy ra lỗi nội bộ.",
}


def message_for(code: str) -> str:
    return _MESSAGES.get(code, _MESSAGES["internal"])


@dataclass(eq=False)
class ApiError(Exception):
    status: int
    code: str
    retryable: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    message: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            self.message = message_for(self.code)
        Exception.__init__(self, f"{self.status} {self.code}")


class UpstreamStatus(Exception):
    """Agent/signer trả non-2xx. `code` lấy từ body lỗi của upstream (nếu có)."""

    def __init__(
        self, source: str, status: int, code: str | None = None, retry_after: str | None = None
    ) -> None:
        super().__init__(f"upstream_status: {source} {status}")
        self.source = source
        self.status = status
        self.code = code
        self.retry_after = retry_after


def _retry_headers(retry_after: str | None) -> dict[str, str]:
    return {"Retry-After": retry_after} if retry_after else {}


def map_upstream(exc: UpstreamStatus) -> ApiError:
    s, src = exc.status, exc.source
    if s == 401:
        return ApiError(401, "session_expired")
    if s == 403:
        if src == "signer":
            log.warning("signer_forbidden", extra={"fields": {"hint": "kiểm tra azp/aud"}})
        return ApiError(403, "forbidden")
    if s == 404:
        return ApiError(404, "not_found")
    if s == 409:
        return ApiError(409, "conflict")
    if s == 410:
        return ApiError(410, "intent_expired")
    if s == 413:
        return ApiError(413, "request_too_large")
    if s == 422 and src == "signer":
        code = exc.code if exc.code in {"intent_mismatch", "intent_unrenderable"} else None
        if code is None and exc.code == "intent_expired":
            return ApiError(410, "intent_expired")
        return ApiError(422, code or "intent_mismatch")
    if s in (400, 422):
        return ApiError(400, "invalid_request")
    if s == 429:
        return ApiError(429, "rate_limited", True, _retry_headers(exc.retry_after))
    return ApiError(502, "upstream_unavailable", True)


def to_http_error(exc: BaseException) -> ApiError:
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, UpstreamStatus):
        return map_upstream(exc)
    if isinstance(exc, TokenExchangeDenied):
        log.warning("token_exchange_denied", extra={"fields": {"reason": exc.reason}})
        return ApiError(502, "upstream_unavailable", True)
    if isinstance(exc, HttpError) and exc.status == 429:
        return ApiError(429, "rate_limited", True)
    if isinstance(exc, TokenServiceUnavailable | HttpError):
        return ApiError(502, "upstream_unavailable", True)
    if isinstance(exc, TokenInvalid):
        return ApiError(401, "session_expired")
    if isinstance(exc, RedisError):
        return ApiError(503, "upstream_unavailable", True)  # fail-closed
    if isinstance(exc, CryptoError):
        return ApiError(401, "session_expired")
    log.error("unhandled_error", extra={"fields": {"exc_type": type(exc).__name__}})
    return ApiError(500, "internal")


def error_body(err: ApiError, request_id: str) -> dict[str, dict[str, object]]:
    return {
        "error": {
            "code": err.code,
            "message": err.message,
            "retryable": err.retryable,
            "request_id": request_id,
        }
    }
