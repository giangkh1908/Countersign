"""Adapter `mock_hash`: embedding giả tất định, không gọi mạng, chuẩn hoá L2.

Mỗi token (tách theo khoảng trắng, chữ thường) băm SHA-256 vào một chiều với dấu +/-; cộng dồn
rồi chuẩn hoá. Văn bản có token chung sẽ có cosine > 0, đủ để test truy xuất mà không cần model.
"""

from __future__ import annotations

import hashlib
import math

from ..ports.embedding_provider import EmbeddingProvider
from ..ports.types import EmbeddingResult


class MockHashEmbeddingProvider(EmbeddingProvider):
    name = "mock_hash"

    def __init__(self, dim: int = 1024) -> None:
        if dim < 1:
            raise ValueError("dim must be >= 1")
        self._dim = dim

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for tok in text.lower().split() or [""]:
            h = hashlib.sha256(tok.encode("utf8")).digest()
            idx = int.from_bytes(h[:4], "big") % self._dim
            v[idx] += 1.0 if h[4] & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v))
        if n == 0:  # các token triệt tiêu nhau: rơi về một chiều cố định
            v[0], n = 1.0, 1.0
        return [x / n for x in v]

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        tokens = sum(max(1, len(t.split())) for t in texts)
        return EmbeddingResult([self._vector(t) for t in texts], tokens)
