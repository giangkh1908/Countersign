"""Điều phối một request `/v1/rerank`: kiểm alias, gọi provider, sắp xếp kết quả, ghi `usage_events`.

Không qua PII/guard. Không ghi nội dung query/documents vào log hay span (chỉ số đếm).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from acme_common.ports import Clock, EventSink
from acme_common.telemetry import start_span

from ..ports.errors import RerankNotConfigured
from ..ports.rerank_provider import RerankProvider
from ..ports.types import ProviderError, RerankItem
from .auth import Caller
from .catalog import ModelCatalog, RerankSpec
from .errors import GatewayError
from .metrics import Metrics
from .pricing import cost_usd, to_micro_usd

log = logging.getLogger("gateway.rerank")

MAX_DOCUMENTS = 100


@dataclass(slots=True)
class ParsedRerank:
    alias: str
    query: str
    documents: list[str]
    top_n: int  # đã kẹp về [1, len(documents)]


def parse_rerank_body(body: Any) -> ParsedRerank:
    """Kiểm schema tối thiểu của body kiểu Jina/Cohere; sai thì `invalid_request`."""
    if not isinstance(body, dict):
        raise GatewayError("invalid_request", "Body must be a JSON object.")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise GatewayError("invalid_request", "'model' is required.")
    query = body.get("query")
    if not isinstance(query, str) or not query:
        raise GatewayError("invalid_request", "'query' must be a non-empty string.")
    docs = body.get("documents")
    if not isinstance(docs, list) or not docs or not all(isinstance(d, str) and d for d in docs):
        raise GatewayError("invalid_request", "'documents' must be a non-empty list of strings.")
    if len(docs) > MAX_DOCUMENTS:
        raise GatewayError("invalid_request", f"'documents' accepts at most {MAX_DOCUMENTS} items.")
    raw_n = body.get("top_n")
    if raw_n is None:
        top_n = len(docs)
    elif isinstance(raw_n, int) and not isinstance(raw_n, bool) and raw_n >= 1:
        top_n = min(raw_n, len(docs))
    else:
        raise GatewayError("invalid_request", "'top_n' must be a positive integer.")
    return ParsedRerank(alias=model, query=query, documents=docs, top_n=top_n)


@dataclass(slots=True)
class RerankResponse:
    body: dict[str, Any]
    headers: dict[str, str]


def _ordered(items: list[RerankItem], n_docs: int, top_n: int) -> list[RerankItem] | None:
    """Sắp giảm dần theo điểm, cắt `top_n`. None nếu runtime trả index sai/trùng."""
    seen: set[int] = set()
    for it in items:
        if not 0 <= it.index < n_docs or it.index in seen:
            return None
        seen.add(it.index)
    return sorted(items, key=lambda it: (-it.score, it.index))[:top_n]


class RerankService:
    def __init__(
        self,
        catalog: ModelCatalog,
        providers: Callable[[RerankSpec], RerankProvider],
        sink: EventSink,
        clock: Clock,
        metrics: Metrics | None = None,
    ) -> None:
        self._catalog = catalog
        self._providers = providers
        self._sink = sink
        self._clock = clock
        self._metrics = metrics or Metrics()

    def _emit(
        self,
        *,
        request_id: str,
        caller: Caller,
        alias: str,
        provider: str | None,
        model: str | None,
        tokens: int,
        status: int,
        error_code: str | None,
        latency_ms: int,
        overhead_ms: int,
        cost: float = 0.0,
    ) -> None:
        """Ghi `usage_events` cùng cột với embeddings (contracts §5); không có output token."""
        event = {
            "event": "usage_event",
            "ts": self._clock.now(),
            "request_id": request_id,
            "key_id": caller.key.key_id,
            "department": caller.dept,
            "end_user_sub": caller.end_user_sub,
            "alias": alias,
            "provider": provider,
            "model": model,
            "input_tokens": tokens,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "cost_micro_usd": to_micro_usd(cost),
            "latency_ms": latency_ms,
            "ttft_ms": None,
            "gateway_overhead_ms": overhead_ms,
            "cache": "miss",
            "status_code": status,
            "error_code": error_code,
        }
        try:
            self._sink.append(event)
        except Exception:  # noqa: BLE001 - sink hỏng không được làm hỏng request
            log.error(
                "usage event dropped", exc_info=True, extra={"fields": {"request_id": request_id}}
            )
        m = self._metrics
        m.requests.labels(alias, str(status)).inc()
        m.tokens.labels("input").inc(tokens)
        m.latency.labels(alias).observe(latency_ms / 1000)

    def _ms(self, since: float) -> int:
        return int((self._clock.monotonic() - since) * 1000)

    async def rerank(self, request_id: str, caller: Caller, parsed: ParsedRerank) -> RerankResponse:
        t0 = self._clock.monotonic()
        if parsed.alias not in caller.key.allowed_models:
            raise GatewayError("model_not_allowed")
        spec = self._catalog.rerank(parsed.alias)
        try:
            provider = self._providers(spec)
        except RerankNotConfigured:
            log.error("rerank provider not configured", extra={"fields": {"alias": spec.alias}})
            raise GatewayError("service_unavailable") from None
        t_call = self._clock.monotonic()
        sp = start_span(
            "gen_ai.rerank",
            **{"gen_ai.request.model": spec.model, "candidates": len(parsed.documents)},
        )
        failure: str | None = None
        ordered: list[RerankItem] = []
        tokens = 0
        try:
            res = await provider.rerank(spec.model, parsed.query, parsed.documents, parsed.top_n)
            got = _ordered(res.items, len(parsed.documents), parsed.top_n)
            if got is None:
                failure = "protocol"
            else:
                ordered, tokens = got, res.prompt_tokens
        except ProviderError as exc:
            failure = exc.kind
        except BaseException as exc:
            sp.set_attribute("error.type", type(exc).__name__)
            sp.end()
            raise
        if failure is not None:
            sp.set_attribute("error.type", failure)
        else:
            sp.set_attribute("returned", len(ordered))
        sp.end()
        total = self._ms(t0)
        common = dict(
            request_id=request_id,
            caller=caller,
            alias=spec.alias,
            provider=provider.name,
            model=spec.model,
            latency_ms=total,
            overhead_ms=max(0, total - self._ms(t_call)),
        )
        if failure is not None:
            log.warning(
                "rerank provider failed",
                extra={"fields": {"provider": provider.name, "kind": failure}},
            )
            self._emit(**common, tokens=0, status=502, error_code="all_providers_failed")
            raise GatewayError("all_providers_failed")
        cost = cost_usd(res.cost_usd, spec.price, tokens)
        self._emit(**common, tokens=tokens, status=200, error_code=None, cost=cost)
        body = {
            "object": "list",
            "model": spec.alias,
            "results": [{"index": it.index, "relevance_score": it.score} for it in ordered],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }
        return RerankResponse(body, {"x-acme-provider": provider.name, "x-acme-model": spec.model})
