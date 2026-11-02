"""Port `DeliveryLog`: sổ gửi tối đa một lần (`report_deliveries`, actions-roles.md §3).

Ghi `sending` TRƯỚC khi gọi kênh; không lưu nội dung, chỉ băm. Mỗi `intent_id` tối đa một dòng
(UNIQUE) nên commit lặp không gửi đúp dù Redis mất trạng thái.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Literal

from acme_common.ports import ExecutionUnavailable
from acme_common.ports.errors import NotConfigured

# sending -> sent | unknown | failed ("failed" = chắc chắn chưa gửi, intent có thể prepare lại)
DeliveryStatus = Literal["sending", "sent", "unknown", "failed"]


class DeliveryLogNotConfigured(NotConfigured):
    pass


class DeliveryLogUnavailable(ExecutionUnavailable):
    """Không ghi/đọc được sổ. `not_written=True`: chắc chắn chưa có dòng nào được ghi (vd không kết nối được)."""

    def __init__(self, kind: str = "unavailable", *, not_written: bool = False) -> None:
        super().__init__(f"delivery_log_unavailable: {kind}")
        self.kind = kind
        self.not_written = not_written


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    intent_id: str
    channel: str
    text_sha256: str
    status: DeliveryStatus
    detail: str = ""


class DeliveryLog(abc.ABC):
    @abc.abstractmethod
    async def begin(
        self, intent_id: str, channel: str, text_sha256: str, actor_sub: str, approval_jti: str
    ) -> None:
        """Ghi `sending`. Raise `DuplicateIntent` nếu `intent_id` đã có dòng;
        `DeliveryLogUnavailable` nếu không ghi được (khi đó CHƯA gửi gì)."""

    @abc.abstractmethod
    async def finish(self, intent_id: str, status: DeliveryStatus, detail: str = "") -> None:
        """Chuyển `sending` sang trạng thái cuối. `detail` là mã ngắn (kind lỗi, mã tin), không nội dung."""

    @abc.abstractmethod
    async def find(self, intent_id: str) -> DeliveryRecord | None:
        """Raise `DeliveryLogUnavailable` nếu không tra được."""
