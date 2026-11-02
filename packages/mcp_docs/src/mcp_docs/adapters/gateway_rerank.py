"""Adapter `Reranker` gọi LLM Gateway: `POST {base}/rerank`, alias `acme-rerank` (kiểu Jina/Cohere).

Plumbing HTTP dùng `RetryingHttpClient` bằng composition. Điểm gateway trả thay `score` của chunk;
chunk gateway không nhắc tới (nếu `top_n` nhỏ hơn số ứng viên) giữ nguyên thứ tự cũ ở cuối.
Mọi lỗi -> `RerankUnavailable(kind)` (message không chứa URL, key hay nội dung).
"""

from __future__ import annotations

import dataclasses

from acme_common.http import HttpError, RetryingHttpClient

from ..ports.reranker import Reranker
from ..ports.types import RerankUnavailable, RetrievedChunk


class GatewayRerankReranker(Reranker):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        http: RetryingHttpClient,
        model: str = "acme-rerank",
    ) -> None:
        self._url = base_url.rstrip("/") + "/rerank"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http
        self._model = model

    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if len(chunks) < 2:
            return chunks
        try:
            resp = await self._http.post(
                self._url,
                json={
                    "model": self._model,
                    "query": query,
                    "documents": [c.content for c in chunks],
                    "top_n": len(chunks),
                },
                headers=self._headers,
            )
        except HttpError as e:
            raise RerankUnavailable(e.kind) from None
        if resp.status_code != 200:
            raise RerankUnavailable(f"http_{resp.status_code}")
        try:
            scored = [
                (int(r["index"]), float(r["relevance_score"])) for r in resp.json()["results"]
            ]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RerankUnavailable("bad_response") from None
        idx = [i for i, _ in scored]
        if len(set(idx)) != len(idx) or any(not 0 <= i < len(chunks) for i in idx):
            raise RerankUnavailable("bad_shape")
        scored.sort(key=lambda t: (-t[1], t[0]))
        out = [dataclasses.replace(chunks[i], score=s) for i, s in scored]
        seen = set(idx)
        out.extend(c for i, c in enumerate(chunks) if i not in seen)
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
