"""Port `DocumentRetriever`: tìm đoạn tài liệu theo quyền của principal."""

from __future__ import annotations

import abc

from acme_common.ports import Principal

from .types import SearchResult


class DocumentRetriever(abc.ABC):
    @abc.abstractmethod
    async def search(
        self,
        query: str,
        principal: Principal,
        k: int,
        department_filter: str | None = None,
    ) -> SearchResult:
        """Chỉ trả đoạn principal được phép xem (ACL do adapter thực thi; service kiểm lại).

        Lỗi hạ tầng => `RetrievalUnavailable`.
        """

    async def verify_schema(  # noqa: B027 - hook tuỳ chọn
        self, expected_dim: int, *, embed_model: str | None = None, strict_meta: bool = False
    ) -> None:
        """Kiểm kho khớp cấu hình lúc khởi động. Sai số chiều => `IndexConfigError`.

        `embed_model` lệch model đã ghi lúc ingest: cảnh báo, hoặc `IndexConfigError` khi `strict_meta`.
        """

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn
        """Giải phóng tài nguyên."""
