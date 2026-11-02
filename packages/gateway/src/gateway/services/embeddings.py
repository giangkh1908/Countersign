"""Điều phối một request `/v1/embeddings`: kiểm alias, gọi provider, dựng response, ghi `usage_events`.

Không qua PII/guard. Không ghi nội dung văn bản đầu vào.
"""

from __future__ import annotations

import base64
import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from acme_common.ports import Clock, EventSink

from ..ports.embedding_provider import EmbeddingProvider
from ..ports.errors import EmbeddingNotConfigured
from ..ports.types import ProviderError
from .auth import Caller
from .catalog import EmbeddingSpec, ModelCatalog
from .errors import GatewayError
from .metrics import Metrics

log = logging.getLogger("gateway.embeddings")

MAX_INPUTS = 32


@dataclass(slots=True)
class ParsedEmbeddings:
    alias: str
    texts: list[str]
    base64: bool = False  # SDK openai mặc định yêu cầu base64 (float32 little-endian)


def parse_embeddings_body(body: Any) -> ParsedEmbeddings:
    """Kiểm schema tối thiểu của body OpenAI; sai thì `invalid_request`."""
    if not isinstance(body, dict):
        raise GatewayError("invalid_request", "Body must be a JSON object.")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise GatewayError("invalid_request", "'model' is required.")
    raw = body.get("input")
    texts = [raw] if isinstance(raw, str) else raw
    if not isinstance(texts, list) or not texts or not all(isinstance(t, str) and t for t in texts):
        raise GatewayError(
            "invalid_request", "'input' must be a non-empty string or list of strings."
        )
    if len(texts) > MAX_INPUTS:
        raise GatewayError("invalid_request", f"'input' accepts at most {MAX_INPUTS} items.")
    fmt = body.get("encoding_format") or "float"
    if fmt not in ("float", "base64"):
        raise GatewayError("invalid_request", "'encoding_format' must be 'float' or 'base64'.")
    return ParsedEmbeddings(alias=model, texts=texts, base64=fmt == "base64")


def _encode(vec: list[float], as_base64: bool) -> list[float] | str:
    if not as_base64:
        return vec
    return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")


@dataclass(slots=True)
class EmbeddingsResult:
    body: dict[str, Any]
    headers: dict[str, str]


class EmbeddingService:
    def __init__(
        self,
        catalog: ModelCatalog,
        providers: Callable[[EmbeddingSpec], EmbeddingProvider],
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
        known_alias: bool,
    ) -> None:
        """Ghi `usage_events` cùng cột với chat (contracts §5); không có output token."""
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
            "cost_micro_usd": 0,
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
        m.requests.labels(alias if known_alias else "unknown", str(status)).inc()
        m.tokens.labels("input").inc(tokens)
        m.latency.labels(alias if known_alias else "unknown").observe(latency_ms / 1000)

    def _ms(self, since: float) -> int:
        return int((self._clock.monotonic() - since) * 1000)

    async def embed(
        self, request_id: str, caller: Caller, parsed: ParsedEmbeddings
    ) -> EmbeddingsResult:
        t0 = self._clock.monotonic()
        if parsed.alias not in caller.key.allowed_models:
            raise GatewayError("model_not_allowed")
        spec = self._catalog.embedding(parsed.alias)
        try:
            provider = self._providers(spec)
        except EmbeddingNotConfigured:
            log.error("embedding provider not configured", extra={"fields": {"alias": spec.alias}})
            raise GatewayError("service_unavailable") from None
        t_call = self._clock.monotonic()
        failure: str | None = None
        try:
            res = await provider.embed(spec.model, parsed.texts)
            if len(res.vectors) != len(parsed.texts) or any(
                len(v) != spec.dim for v in res.vectors
            ):
                failure = "protocol"  # sai số vector hoặc số chiều so với schema
        except ProviderError as exc:
            failure = exc.kind
        total = self._ms(t0)
        common = dict(
            request_id=request_id,
            caller=caller,
            alias=spec.alias,
            provider=provider.name,
            model=spec.model,
            latency_ms=total,
            overhead_ms=max(0, total - self._ms(t_call)),
            known_alias=True,
        )
        if failure is not None:
            log.warning(
                "embedding provider failed",
                extra={"fields": {"provider": provider.name, "kind": failure}},
            )
            self._emit(**common, tokens=0, status=502, error_code="all_providers_failed")
            raise GatewayError("all_providers_failed")
        self._emit(**common, tokens=res.prompt_tokens, status=200, error_code=None)
        body = {
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": _encode(v, parsed.base64)}
                for i, v in enumerate(res.vectors)
            ],
            "model": spec.alias,
            "usage": {"prompt_tokens": res.prompt_tokens, "total_tokens": res.prompt_tokens},
        }
        return EmbeddingsResult(
            body, {"x-acme-provider": provider.name, "x-acme-model": spec.model}
        )
