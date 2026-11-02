"""Port `MessageChannel`: gửi một tin văn bản vào một cuộc trò chuyện (actions-roles.md §3).

Adapter: `telegram`, `fake` (test và eval). Slack, Zalo OA thêm bằng một file adapter mới.

Hợp đồng lỗi: adapter chỉ ném `ChannelSendError(kind, status)`. Message KHÔNG chứa URL, header, body
hay exception gốc, vì URL của một số kênh mang token (Telegram Bot API). `delivered` là phán đoán
về việc tin đã đi chưa:
- `"no"`: chắc chắn chưa gửi (lỗi kết nối trước khi request đi, bị từ chối 4xx, 429).
- `"unknown"`: không biết (timeout sau khi gửi, 5xx, lỗi giao thức). KHÔNG được tự gửi lại.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Literal

from acme_common.ports.errors import NotConfigured

# kind thuộc tập hữu hạn, an toàn để log
ERROR_KINDS = frozenset(
    {
        "connect",
        "timeout",
        "transport",
        "rate_limited",
        "http_4xx",
        "http_5xx",
        "bad_response",
        "not_configured",
        "internal",
    }
)


class MessageChannelNotConfigured(NotConfigured):
    pass


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Biên nhận của kênh. `message_ref` là mã tin phía kênh (không bí mật), có thể rỗng."""

    message_ref: str = ""


class ChannelSendError(Exception):
    """Gửi lỗi. Chỉ mang `kind` và `status`; không có URL hay exception gốc."""

    def __init__(
        self,
        kind: str,
        *,
        status: int | None = None,
        delivered: Literal["no", "unknown"] = "unknown",
        retry_after_s: float | None = None,
    ) -> None:
        if kind not in ERROR_KINDS:
            kind = "internal"
        super().__init__(f"channel_send_error: {kind}" + (f" status={status}" if status else ""))
        self.kind = kind
        self.status = status
        self.delivered = delivered
        self.retry_after_s = retry_after_s

    @property
    def safe_to_retry(self) -> bool:
        """Chỉ khi chắc chắn chưa gửi VÀ lỗi có thể qua đi (kết nối, 429)."""
        return self.delivered == "no" and self.kind in ("connect", "rate_limited")


class MessageChannel(abc.ABC):
    @abc.abstractmethod
    async def send(self, chat_ref: str, text: str) -> DeliveryReceipt:
        """Gửi `text` nguyên văn (văn bản thuần, không định dạng, tắt xem trước link).

        `chat_ref` là tham chiếu cấu hình của kênh (adapter tự tra ra chat ID thật).
        Raise `ChannelSendError`; không bao giờ tự thử lại một lần gửi có thể đã đi.
        """
