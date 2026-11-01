"""Port `DocumentIndexer`: ghi tài liệu + chunk đã embed vào kho (bước [5] của ingest)."""

from __future__ import annotations

import abc
from dataclasses import dataclass

from .types import Chunk, DocumentMeta


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    chunk: Chunk
    embedding: list[float]


class DocumentIndexer(abc.ABC):
    @abc.abstractmethod
    async def is_current(self, meta: DocumentMeta) -> bool:
        """`True` nếu tài liệu đã có chunk và sha256 + metadata ACL không đổi (bỏ qua ingest)."""

    @abc.abstractmethod
    async def replace(self, meta: DocumentMeta, chunks: list[IndexedChunk]) -> None:
        """Thay toàn bộ chunk của tài liệu trong MỘT transaction; `version+1` nếu nội dung đổi."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn
        """Giải phóng tài nguyên."""
