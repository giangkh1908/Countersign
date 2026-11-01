"""Điều phối một request chat: kiểm alias, gọi provider, dựng response, ghi `usage_events`.

Gateway mỏng: không rate limit, budget, cache, PII, guard, fallback hay breaker (chỉ dùng phần tử
đầu của chain). Không ghi nội dung prompt/response.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from acme_common.ports import Clock, EventSink

from ..ports.chat_provider import ChatProvider
from ..ports.errors import ProviderNotConfigured
from ..ports.types import ChatRequest, ProviderError, Usage
from .auth import Caller
from .catalog import ModelCatalog, Resolved
from .encoder import StreamEncoder, completion_body, sse
from .errors import GatewayError
from .metrics import Metrics

log = logging.getLogger("gateway.chat")

# OpenAI params mà v1 bỏ lặng lẽ (trả header x-acme-ignored-params)
_IGNORED = (
    "logprobs",
    "top_logprobs",
    "logit_bias",
    "seed",
    "presence_penalty",
    "frequency_penalty",
    "response_format",
    "user",
)
_PARAMS = ("temperature", "top_p", "stop", "parallel_tool_calls")


@dataclass(slots=True)
class ParsedChat:
    alias: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    tool_choice: str | dict[str, Any] | None
    params: dict[str, Any]
    stream: bool
    include_usage: bool
    ignored: list[str] = field(default_factory=list)


def parse_chat_body(body: Any) -> ParsedChat:
    """Kiểm schema tối thiểu của body OpenAI; sai thì `invalid_request`."""
    if not isinstance(body, dict):
        raise GatewayError("invalid_request", "Body must be a JSON object.")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise GatewayError("invalid_request", "'model' is required.")
    messages = body.get("messages")
    if (
        not isinstance(messages, list)
        or not messages
        or not all(isinstance(m, dict) and isinstance(m.get("role"), str) for m in messages)
    ):
        raise GatewayError("invalid_request", "'messages' must be a non-empty list of messages.")
    if (body.get("n") or 1) != 1:
        raise GatewayError("invalid_request", "'n' > 1 is not supported.")
    tools = body.get("tools")
    if tools is not None and (
        not isinstance(tools, list) or not all(isinstance(t, dict) for t in tools)
    ):
        raise GatewayError("invalid_request", "'tools' must be a list.")
    stream = bool(body.get("stream", False))
    opts = body.get("stream_options")
    include_usage = bool(opts.get("include_usage")) if isinstance(opts, dict) else False
    params: dict[str, Any] = {k: body[k] for k in _PARAMS if body.get(k) is not None}
    max_tokens = body.get("max_completion_tokens") or body.get("max_tokens")
    if max_tokens is not None:
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise GatewayError("invalid_request", "'max_tokens' must be a positive integer.")
        params["max_tokens"] = max_tokens
    return ParsedChat(
        alias=model,
        messages=messages,
        tools=tools or None,
        tool_choice=body.get("tool_choice"),
        params=params,
        stream=stream,
        include_usage=include_usage,
        ignored=[k for k in _IGNORED if k in body],
    )


@dataclass(slots=True)
class ChatResult:
    body: dict[str, Any]
    headers: dict[str, str]


@dataclass(slots=True)
class StreamResult:
    events: AsyncIterator[str]
    headers: dict[str, str]


class ChatService:
    def __init__(
        self,
        catalog: ModelCatalog,
        providers: Callable[[str], ChatProvider],
        sink: EventSink,
        clock: Clock,
        metrics: Metrics | None = None,
    ) -> None:
        self._catalog = catalog
        self._providers = providers
        self._sink = sink
        self._clock = clock
        self._metrics = metrics or Metrics()

    # ---------- chung ----------

    def _prepare(
        self, caller: Caller, parsed: ParsedChat
    ) -> tuple[Resolved, ChatProvider, ChatRequest]:
        if parsed.alias not in caller.key.allowed_models:
            raise GatewayError("model_not_allowed")
        resolved = self._catalog.resolve(parsed.alias)
        ref = resolved.chain[0]  # chưa có fallback
        try:
            provider = self._providers(ref.provider)
        except ProviderNotConfigured:
            log.error("provider not configured", extra={"fields": {"provider": ref.provider}})
            raise GatewayError("service_unavailable") from None
        params = dict(parsed.params)
        params.setdefault("max_tokens", resolved.default_max_output)
        req = ChatRequest(
            alias=resolved.alias,
            model=ref.model,
            messages=parsed.messages,
            tools=parsed.tools,
            tool_choice=parsed.tool_choice,
            params=params,
            stream=parsed.stream,
        )
        return resolved, provider, req

    def _emit(
        self,
        *,
        request_id: str,
        caller: Caller,
        resolved: Resolved | None,
        requested_alias: str,
        provider: str | None,
        model: str | None,
        usage: Usage | None,
        status: int,
        error_code: str | None,
        latency_ms: int,
        overhead_ms: int,
        ttft_ms: int | None,
    ) -> None:
        """Ghi `usage_events` (cột theo contracts §5). Không chứa nội dung prompt."""
        u = usage or Usage()
        alias = resolved.alias if resolved else requested_alias
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
            "input_tokens": u.prompt_tokens,
            "output_tokens": u.completion_tokens,
            "cached_input_tokens": u.cached_tokens,
            "cost_micro_usd": 0,  # chưa có bảng giá
            "latency_ms": latency_ms,
            "ttft_ms": ttft_ms,
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
        label = alias if resolved else "unknown"
        m.requests.labels(label, str(status)).inc()
        m.tokens.labels("input").inc(u.prompt_tokens)
        m.tokens.labels("output").inc(u.completion_tokens)
        m.latency.labels(label).observe(latency_ms / 1000)

    def _headers(
        self, request_id: str, provider: str, model: str, parsed: ParsedChat
    ) -> dict[str, str]:
        h = {
            "x-acme-provider": provider,
            "x-acme-model": model,
        }
        if parsed.ignored:
            h["x-acme-ignored-params"] = ",".join(parsed.ignored)
        return h

    def _ms(self, since: float) -> int:
        return int((self._clock.monotonic() - since) * 1000)

    # ---------- non-stream ----------

    async def complete(self, request_id: str, caller: Caller, parsed: ParsedChat) -> ChatResult:
        t0 = self._clock.monotonic()
        resolved, provider, req = self._prepare(caller, parsed)
        t_call = self._clock.monotonic()
        try:
            resp = await provider.complete(req)
        except ProviderError as exc:
            self._provider_failed(request_id, caller, resolved, provider, req, exc, t0, t_call)
            raise GatewayError("all_providers_failed") from None
        call_ms = self._ms(t_call)
        total = self._ms(t0)
        self._emit(
            request_id=request_id,
            caller=caller,
            resolved=resolved,
            requested_alias=parsed.alias,
            provider=provider.name,
            model=req.model,
            usage=resp.usage,
            status=200,
            error_code=None,
            latency_ms=total,
            overhead_ms=max(0, total - call_ms),
            ttft_ms=None,
        )
        created = int(self._clock.now().timestamp())
        return ChatResult(
            completion_body(request_id, parsed.alias, created, resp),
            self._headers(request_id, provider.name, req.model, parsed),
        )

    def _provider_failed(
        self,
        request_id: str,
        caller: Caller,
        resolved: Resolved,
        provider: ChatProvider,
        req: ChatRequest,
        exc: ProviderError,
        t0: float,
        t_call: float,
    ) -> None:
        log.warning(
            "provider failed", extra={"fields": {"provider": provider.name, "kind": exc.kind}}
        )
        total = self._ms(t0)
        self._emit(
            request_id=request_id,
            caller=caller,
            resolved=resolved,
            requested_alias=resolved.requested,
            provider=provider.name,
            model=req.model,
            usage=None,
            status=502,
            error_code="all_providers_failed",
            latency_ms=total,
            overhead_ms=max(0, total - self._ms(t_call)),
            ttft_ms=None,
        )

    # ---------- stream ----------

    async def stream(self, request_id: str, caller: Caller, parsed: ParsedChat) -> StreamResult:
        """Lấy chunk đầu TRƯỚC khi trả response: lỗi trước byte đầu thành HTTP error đúng nghĩa."""
        t0 = self._clock.monotonic()
        resolved, provider, req = self._prepare(caller, parsed)
        t_call = self._clock.monotonic()
        it = provider.stream(req)
        try:
            first = await anext(it)
        except (ProviderError, StopAsyncIteration) as exc:
            await it.aclose()
            err = exc if isinstance(exc, ProviderError) else ProviderError("protocol")
            self._provider_failed(request_id, caller, resolved, provider, req, err, t0, t_call)
            raise GatewayError("all_providers_failed") from None
        except BaseException:
            await it.aclose()
            raise
        ttft = self._ms(t_call)
        return StreamResult(
            self._run_stream(
                request_id, caller, parsed, resolved, provider, req, it, first, t0, t_call, ttft
            ),
            self._headers(request_id, provider.name, req.model, parsed),
        )

    async def _run_stream(
        self,
        request_id: str,
        caller: Caller,
        parsed: ParsedChat,
        resolved: Resolved,
        provider: ChatProvider,
        req: ChatRequest,
        it: AsyncIterator[Any],
        first: Any,
        t0: float,
        t_call: float,
        ttft: int,
    ) -> AsyncIterator[str]:
        enc = StreamEncoder(
            request_id, parsed.alias, int(self._clock.now().timestamp()), parsed.include_usage
        )
        usage = Usage()
        status, error_code = 200, None
        try:
            chunk: Any = first
            while True:
                if chunk.usage is not None:
                    usage = chunk.usage
                for line in enc.encode(chunk):
                    yield line
                try:
                    chunk = await anext(it)
                except StopAsyncIteration:
                    break
            x_acme = {
                "request_id": request_id,
                "cost_usd": 0.0,
                "fallbacks": 0,
                "provider": provider.name,
                "model": req.model,
            }
            for line in enc.finish(usage, x_acme):
                yield line
        except ProviderError as exc:
            log.warning("provider failed mid-stream", extra={"fields": {"kind": exc.kind}})
            status, error_code = 502, "all_providers_failed"
            err = GatewayError("all_providers_failed")
            yield sse(err.body())
            yield sse("[DONE]")
        except (asyncio.CancelledError, GeneratorExit):
            status, error_code = 499, "client_disconnected"
            usage.estimated = True
            raise
        finally:
            total = self._ms(t0)
            self._emit(
                request_id=request_id,
                caller=caller,
                resolved=resolved,
                requested_alias=parsed.alias,
                provider=provider.name,
                model=req.model,
                usage=usage,
                status=status,
                error_code=error_code,
                latency_ms=total,
                overhead_ms=max(0, total - self._ms(t_call)),
                ttft_ms=ttft,
            )
            await it.aclose()
