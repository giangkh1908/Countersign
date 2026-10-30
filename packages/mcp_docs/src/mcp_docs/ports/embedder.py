"""Port `Embedder`: văn bản -> vector đã L2-normalize (contracts §9.2, §5 alias `acme-embed`).

Adapter: `gateway_http` (gọi gateway `/v1/embeddings`), `fake_hash` (tất định, dev/test).
Ingest và query phải dùng CÙNG một adapter (D2: một runtime embedding duy nhất).
"""

from __future__ import annotations

import abc


class Embedder(abc.ABC):
    @property
    @abc.abstractmethod
    def dim(self) -> int:
        """Số chiều vector (phải khớp cột `chunks.embedding`)."""

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Một vector cho mỗi text, cùng thứ tự. Lỗi => `EmbeddingUnavailable`."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn
        """Giải phóng tài nguyên (client HTTP...)."""
