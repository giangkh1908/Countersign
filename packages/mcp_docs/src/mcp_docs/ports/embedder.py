"""Port `Embedder`: văn bản -> vector đã L2-normalize (contracts §9.2; alias `acme-embed` ở contracts §8).

Adapter: `gateway_http` (gọi gateway `/v1/embeddings`), `fake_hash` (tất định, dev/test).
Ingest và query phải dùng CÙNG một adapter (một runtime embedding duy nhất).
"""

from __future__ import annotations

import abc


class Embedder(abc.ABC):
    @property
    @abc.abstractmethod
    def dim(self) -> int:
        """Số chiều vector (phải khớp cột `chunks.embedding`)."""

    @property
    @abc.abstractmethod
    def model_id(self) -> str:
        """Id model thật đứng sau embedder (không phải alias cấu hình), dùng cho `index_sig`/`index_meta`.

        Có thể chỉ biết sau lần `embed` thành công đầu tiên; trước đó trả giá trị cấu hình.
        """

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Một vector cho mỗi text, cùng thứ tự. Lỗi => `EmbeddingUnavailable`."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn
        """Giải phóng tài nguyên (client HTTP...)."""
