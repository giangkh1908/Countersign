"""Port `Reranker`: sắp xếp lại ứng viên. Adapter hiện có: `none`."""

from __future__ import annotations

import abc

from .types import RetrievedChunk


class Reranker(abc.ABC):
    @abc.abstractmethod
    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...
