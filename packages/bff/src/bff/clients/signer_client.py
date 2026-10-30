"""SignerClient: verify_intent, approve (05 §5.3). Lớp HTTP thường, KHÔNG có khoá ký.

`approval_token` chỉ đi từ đây vào lời gọi resume của agent; không log, không trả trình duyệt.
"""

from __future__ import annotations

from typing import Any

from acme_common.http import HttpError, RetryingHttpClient

from ..services.errors import ApiError, UpstreamStatus
from .agent_client import auth_headers, error_code_of


class SignerClient:
    def __init__(self, base_url: str, http: RetryingHttpClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http

    async def _post(self, path: str, token: str, intent_jws: str) -> dict[str, Any]:
        try:
            resp = await self._http.post(
                f"{self._base}{path}", json={"intent_jws": intent_jws}, headers=auth_headers(token)
            )
        except HttpError as exc:
            if exc.kind == "connection":
                # signer vắng mặt (profile `tickets` tắt): lỗi phụ thuộc rõ ràng (503), BFF vẫn khoẻ.
                raise ApiError(503, "upstream_unavailable", True) from None
            raise
        if resp.status_code >= 400:
            raise UpstreamStatus(
                "signer", resp.status_code, error_code_of(resp), resp.headers.get("retry-after")
            )
        try:
            body = resp.json()
        except ValueError:
            raise HttpError("bad_body", retryable=False) from None
        if not isinstance(body, dict):
            raise HttpError("bad_body", retryable=False)
        return body

    async def verify_intent(self, intent_jws: str, token: str) -> dict[str, Any]:
        return await self._post("/v1/intents/verify", token, intent_jws)

    async def approve(self, intent_jws: str, token: str) -> dict[str, Any]:
        return await self._post("/v1/approvals", token, intent_jws)
