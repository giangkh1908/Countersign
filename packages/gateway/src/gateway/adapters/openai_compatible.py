"""Adapter `openai_compatible`: `POST {base_url}/embeddings` (chuẩn mở, đổi vendor chỉ đổi config).

Plumbing HTTP (retry, timeout) dùng `RetryingHttpClient` bằng composition. Mọi lỗi -> `ProviderError`
với message không chứa URL, key hay nội dung.
"""

from __future__ import annotations

from typing import Any

from acme_common.http import HttpError, RetryingHttpClient

from ..ports.embedding_provider import EmbeddingProvider
from ..ports.types import EmbeddingResult, ProviderError
from ._cost import reported_cost


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str | None, http: RetryingHttpClient) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        try:
            resp = await self._http.post(
                self._url,
                json={"model": model, "input": texts, "encoding_format": "float"},
                headers=self._headers,
            )
        except HttpError as e:
            raise ProviderError(e.kind, retryable=e.retryable) from None
        if resp.status_code != 200:
            raise ProviderError(f"http_{resp.status_code}")
        try:
            body = resp.json()
            data: list[dict[str, Any]] = sorted(body["data"], key=lambda d: d["index"])
            vecs = [[float(x) for x in d["embedding"]] for d in data]
            usage = body.get("usage") or {}
            tokens = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        except (ValueError, KeyError, TypeError):
            raise ProviderError("protocol") from None
        if len(vecs) != len(texts):
            raise ProviderError("protocol")
        return EmbeddingResult(vecs, tokens, reported_cost(usage))

    async def aclose(self) -> None:
        await self._http.aclose()
