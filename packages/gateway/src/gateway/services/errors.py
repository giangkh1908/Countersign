"""`GatewayError` và bảng mã lỗi (contracts §6.1). Format OpenAI: `{"error":{"message","type","code"}}`."""

from __future__ import annotations

from typing import Any

# code -> (HTTP status, type kiểu OpenAI, message cố định không lộ chi tiết)
_CODES: dict[str, tuple[int, str, str]] = {
    "invalid_request": (400, "invalid_request_error", "Invalid request."),
    "invalid_api_key": (401, "authentication_error", "Invalid API key."),
    "key_revoked": (401, "authentication_error", "API key has been revoked."),
    "key_expired": (401, "authentication_error", "API key has expired."),
    "invalid_end_user_token": (401, "authentication_error", "Invalid end-user token."),
    "forbidden": (403, "permission_error", "Forbidden."),
    "model_not_allowed": (403, "permission_error", "Model alias is not allowed for this key."),
    "not_found": (404, "invalid_request_error", "Not found."),
    "request_too_large": (413, "invalid_request_error", "Request body too large."),
    "internal_error": (500, "server_error", "Internal server error."),
    "all_providers_failed": (502, "server_error", "All providers failed."),
    "service_unavailable": (503, "server_error", "Service unavailable."),
}


class GatewayError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        status: int | None = None,
    ) -> None:
        http_status, etype, default_msg = _CODES[code]
        super().__init__(code)
        self.code = code
        self.status = status or http_status
        self.type = etype
        self.message = message or default_msg
        self.headers = headers or {}

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.type,
                "param": None,
                "code": self.code,
            }
        }
