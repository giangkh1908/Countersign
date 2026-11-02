"""Port `Reranker`: sắp xếp lại ứng viên. Adapter: `none`, `gateway_rerank`."""

from __future__ import annotations

import abc

from .types import RetrievedChunk


class Reranker(abc.ABC):
    #: False => adapter giữ nguyên thứ tự (không đổi `reranked` trong output, không nới số ứng viên)
    active: bool = True

    @abc.abstractmethod
    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Trả lại đúng các chunk đầu vào theo thứ tự mới. Raise `RerankUnavailable` khi lỗi."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn, không bắt buộc override
        """Đóng tài nguyên (client HTTP). Mặc định không làm gì."""
