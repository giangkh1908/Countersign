"""Port `DocumentIndexer`: ghi tài liệu + chunk đã embed vào kho (bước [5] của ingest)."""

from __future__ import annotations

import abc
from dataclasses import dataclass

from .types import Chunk, DocumentMeta


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    chunk: Chunk
    embedding: list[float]
    fts_text: str | None = None  # văn bản đã tách từ cho full-text; None khi không tính


class DocumentIndexer(abc.ABC):
    @abc.abstractmethod
    async def is_current(self, meta: DocumentMeta, index_sig: str = "") -> bool:
        """`True` nếu tài liệu đã có chunk và sha256, metadata ACL, `index_sig` đều không đổi."""

    @abc.abstractmethod
    async def replace(
        self, meta: DocumentMeta, chunks: list[IndexedChunk], index_sig: str = ""
    ) -> None:
        """Thay toàn bộ chunk của tài liệu trong MỘT transaction; `version+1` nếu nội dung đổi."""

    async def verify_schema(self, expected_dim: int) -> None:  # noqa: B027 - hook tuỳ chọn
        """Kiểm kho khớp cấu hình trước khi ghi. Sai số chiều => `IndexConfigError`."""

    async def record_index_meta(self, values: dict[str, str]) -> None:  # noqa: B027 - hook tuỳ chọn
        """Ghi model/chiều/phiên bản chunker đã dùng (chống lẫn vector của hai model)."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn
        """Giải phóng tài nguyên."""
