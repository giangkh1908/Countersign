"""Adapter `Embedder` gọi LLM Gateway: `POST {base}/embeddings`, alias `acme-embed` (OpenAI-compatible).

Plumbing HTTP dùng `RetryingHttpClient` bằng composition. Gateway chuyển tiếp tới runtime embedding
duy nhất (D2); ingest và query dùng cùng adapter này. Lỗi mọi loại -> `EmbeddingUnavailable(kind)`
(message không chứa URL, key hay nội dung).
"""

from __future__ import annotations

import math
from typing import Any

from acme_common.http import HttpError, RetryingHttpClient

from ..ports.embedder import Embedder
from ..ports.types import EmbeddingUnavailable

BATCH = 32  # 02 §5.1 [4]: tối đa 32 chunk/request


class GatewayHttpEmbedder(Embedder):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        http: RetryingHttpClient,
        model: str = "acme-embed",
        dim: int = 1024,
    ) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http
        self._model = model
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(await self._batch(texts[i : i + BATCH]))
        return out

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = await self._http.post(
                self._url,
                json={"model": self._model, "input": texts, "encoding_format": "float"},
                headers=self._headers,
            )
        except HttpError as e:
            raise EmbeddingUnavailable(e.kind) from None
        if resp.status_code != 200:
            raise EmbeddingUnavailable(f"http_{resp.status_code}")
        try:
            data: list[dict[str, Any]] = sorted(resp.json()["data"], key=lambda d: d["index"])
            vecs = [[float(x) for x in d["embedding"]] for d in data]
        except (ValueError, KeyError, TypeError):
            raise EmbeddingUnavailable("bad_response") from None
        if len(vecs) != len(texts) or any(len(v) != self._dim for v in vecs):
            raise EmbeddingUnavailable("bad_shape")
        return [_normalize(v) for v in vecs]

    async def aclose(self) -> None:
        await self._http.aclose()


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v
