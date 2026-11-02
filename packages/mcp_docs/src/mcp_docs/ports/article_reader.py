"""Port `ArticleReader`: tra trực tiếp chunk theo (số hiệu, Điều[, khoản]) trong phạm vi quyền."""

from __future__ import annotations

import abc

from acme_common.ports import Principal

from .types import Ref, RetrievedChunk


class ArticleReader(abc.ABC):
    @abc.abstractmethod
    async def read(self, refs: list[Ref], principal: Principal) -> list[RetrievedChunk]:
        """Chunk của mỗi `Ref` có `doc_num` và `article`, theo `ord`; chỉ trả phần principal được xem.

        ACL do adapter thực thi (không có đường tắt bỏ qua quyền). Lỗi hạ tầng => `RetrievalUnavailable`.
        """

    @abc.abstractmethod
    async def find_documents(self, hint: str, principal: Principal) -> list[tuple[str, str]]:
        """`[(doc_num, title)]` của văn bản principal được xem có tên khớp `hint` (không phân biệt dấu).

        Có khớp nguyên tên thì chỉ trả các khớp nguyên tên. Văn bản không có `doc_num` bị bỏ qua.
        """

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn
        """Giải phóng tài nguyên."""
