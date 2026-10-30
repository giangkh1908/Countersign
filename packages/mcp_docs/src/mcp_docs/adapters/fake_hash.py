"""Adapter `Embedder` tất định: hashing trick trên từ + n-gram ký tự (dev và test, M1 mặc định).

Không phải embedding ngữ nghĩa: chỉ phản ánh trùng lặp từ/n-gram bề mặt (sau NFC, chữ thường, bỏ
dấu). Cùng văn bản => cùng vector trên mọi máy (blake2b, không phụ thuộc PYTHONHASHSEED).
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata

from ..ports.embedder import Embedder

_WORD = re.compile(r"\w+", re.UNICODE)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return unicodedata.normalize("NFC", "".join(c for c in t if not unicodedata.combining(c)))


class FakeHashEmbedder(Embedder):
    def __init__(self, dim: int = 1024, ngram: int = 3) -> None:
        self._dim = dim
        self._n = ngram

    @property
    def dim(self) -> int:
        return self._dim

    def _features(self, text: str) -> list[str]:
        feats: list[str] = []
        for w in _WORD.findall(_fold(text)):
            feats.append("w:" + w)
            padded = f"^{w}$"
            feats.extend(
                "g:" + padded[i : i + self._n] for i in range(max(1, len(padded) - self._n + 1))
            )
        return feats

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for f in self._features(text):
            h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self._dim
            vec[idx] += 1.0 if h[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]
