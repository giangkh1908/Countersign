"""Port `RerankProvider`: `rerank(model, query, documents, top_n)`.

Không thuộc chuẩn OpenAI nên đi qua port riêng (rag-citations §4.6). Adapter v1: `http_rerank`
(API kiểu Jina/Cohere/llama.cpp). Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import abc

from .types import RerankResult


class RerankProvider(abc.ABC):
    #: tên adapter ghi vào `usage_events.provider` và header `x-acme-provider`
    name: str = "unknown"

    @abc.abstractmethod
    async def rerank(
        self, model: str, query: str, documents: list[str], top_n: int
    ) -> RerankResult:
        """`model` là id model của provider (đã resolve từ alias). Raise `ProviderError`."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn, không bắt buộc override
        """Đóng tài nguyên (client HTTP). Mặc định không làm gì."""
