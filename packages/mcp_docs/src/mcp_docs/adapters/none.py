"""Adapter `Reranker` không rerank: giữ thứ tự RRF (mặc định)."""

from __future__ import annotations

from ..ports.reranker import Reranker
from ..ports.types import RetrievedChunk


class NoReranker(Reranker):
    active = False

    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return chunks
