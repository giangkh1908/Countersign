"""Port `Reranker`: sắp xếp lại ứng viên. Adapter M1: `none`."""

from __future__ import annotations

import abc

from .types import RetrievedChunk


class Reranker(abc.ABC):
    @abc.abstractmethod
    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...
