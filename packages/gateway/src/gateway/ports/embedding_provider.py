"""Port `EmbeddingProvider`: `embed(model, texts)`.

Adapter v1: `mock_hash` (tất định, không mạng) và `openai_compatible` (chuẩn mở: đổi vendor chỉ đổi config).
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import abc

from .types import EmbeddingResult


class EmbeddingProvider(abc.ABC):
    #: tên adapter ghi vào `usage_events.provider` và header `x-acme-provider`
    name: str = "unknown"

    @abc.abstractmethod
    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        """`model` là id model của provider (đã resolve từ alias). Raise `ProviderError`."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn, không bắt buộc override
        """Đóng tài nguyên (client HTTP). Mặc định không làm gì."""
