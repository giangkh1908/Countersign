"""Adapter `Reranker` không rerank: giữ thứ tự RRF (mặc định M1)."""

from __future__ import annotations

from ..ports.reranker import Reranker
from ..ports.types import RetrievedChunk


class NoReranker(Reranker):
    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return chunks
