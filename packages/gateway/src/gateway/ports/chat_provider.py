"""Port `ChatProvider`: `complete(req)`, `stream(req)`.

Adapter v1: xem bảng §9.2 (M1: provider thật đầu tiên + `mock`; provider thứ hai: M2). Decorator Retrying/CircuitBreaking/Fallback/Metered: M2.
Tài liệu: docs/design/00-contracts.md §9.2, 01 §1.2/§7.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator

from .types import ChatChunk, ChatRequest, ChatResponse


class ChatProvider(abc.ABC):
    #: tên provider ghi vào `usage_events.provider` và header `x-acme-provider`
    name: str = "unknown"

    @abc.abstractmethod
    async def complete(self, req: ChatRequest) -> ChatResponse:
        """Raise `ProviderError`."""

    @abc.abstractmethod
    def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Async generator. Raise `ProviderError` (trước hoặc giữa chừng stream)."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn, không bắt buộc override
        """Đóng tài nguyên (client HTTP). Mặc định không làm gì."""
