"""Adapter `http_rerank`: `POST {base_url}{path}` kiểu Jina/Cohere/llama.cpp (`llama-server --reranking`).

Request `{model, query, documents, top_n}` -> `{results: [{index, relevance_score}], usage?}`.
Plumbing HTTP dùng `RetryingHttpClient` bằng composition. Mọi lỗi -> `ProviderError` với message
không chứa URL, key hay nội dung.
"""

from __future__ import annotations

from acme_common.http import HttpError, RetryingHttpClient

from ..ports.rerank_provider import RerankProvider
from ..ports.types import ProviderError, RerankItem, RerankResult
from ._cost import reported_cost


class HttpRerankProvider(RerankProvider):
    name = "http_rerank"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        http: RetryingHttpClient,
        path: str = "/v1/rerank",
    ) -> None:
        self._url = base_url.rstrip("/") + "/" + path.lstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http

    async def rerank(
        self, model: str, query: str, documents: list[str], top_n: int
    ) -> RerankResult:
        try:
            resp = await self._http.post(
                self._url,
                json={"model": model, "query": query, "documents": documents, "top_n": top_n},
                headers=self._headers,
            )
        except HttpError as e:
            raise ProviderError(e.kind, retryable=e.retryable) from None
        if resp.status_code != 200:
            raise ProviderError(f"http_{resp.status_code}")
        try:
            body = resp.json()
            items = [
                RerankItem(int(r["index"]), float(r["relevance_score"])) for r in body["results"]
            ]
            usage = body.get("usage") or {}
            tokens = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("protocol") from None
        return RerankResult(items, tokens, reported_cost(usage))

    async def aclose(self) -> None:
        await self._http.aclose()
