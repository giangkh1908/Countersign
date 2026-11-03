"""Điều phối một request chat: kiểm alias, gọi provider, dựng response, ghi `usage_events`.

Gateway mỏng: không rate limit, budget, PII, guard, fallback hay breaker (chỉ dùng phần tử
đầu của chain). Exact cache (tuỳ chọn, `ResponseCache`) đặt ngay sau `_prepare`, sau khi kiểm
quyền model. Không ghi nội dung prompt/response vào log, span, metric.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from acme_common.ports import Clock, EventSink
from acme_common.telemetry import start_span

from ..ports.chat_provider import ChatProvider
from ..ports.errors import ProviderNotConfigured
from ..ports.response_cache import CachedResponse, ResponseCache
from ..ports.types import ChatChunk, ChatRequest, ChatResponse, ProviderError, Usage
from .auth import Caller
from .cache_key import build_cache_key
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


def _chat_span(model: str, cache: str = "miss") -> Any:
    """Span `gen_ai.chat`: chỉ model, token, cache, finish_reason; không nội dung prompt/response."""
    return start_span("gen_ai.chat", **{"gen_ai.request.model": model, "cache": cache})


def _end_chat_span(
    sp: Any, usage: Usage | None, finish_reason: str | None, error: str | None = None
) -> None:
    if usage is not None:
        sp.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)
        sp.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)
    if finish_reason:
        sp.set_attribute("finish_reason", finish_reason)
    if error:
        sp.set_attribute("error.type", error)
    sp.end()


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
        *,
        cache: ResponseCache | None = None,
        cache_ttl_s: int = 3600,
        cache_index_version: str = "0",
    ) -> None:
        self._cache = cache
        self._cache_ttl_s = cache_ttl_s
        self._cache_ver = cache_index_version
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
            extra_body=resolved.extra_body,
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
        cache: str = "miss",
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
            "cache": cache,
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
        self, request_id: str, provider: str, model: str, parsed: ParsedChat, cache: str | None
    ) -> dict[str, str]:
        h = {
            "x-acme-provider": provider,
            "x-acme-model": model,
        }
        if cache:
            h["x-acme-cache"] = cache
        if parsed.ignored:
            h["x-acme-ignored-params"] = ",".join(parsed.ignored)
        return h

    def _ms(self, since: float) -> int:
        return int((self._clock.monotonic() - since) * 1000)

    # ---------- exact cache ----------

    def _cache_key(
        self, caller: Caller, parsed: ParsedChat, provider: ChatProvider, req: ChatRequest
    ) -> str | None:
        """Khoá cache, hoặc None nếu không cache (cache tắt / request không đủ điều kiện)."""
        if self._cache is None:
            return None
        key = build_cache_key(
            user=caller.user,
            provider=provider.name,
            model=req.model,
            messages=req.messages,
            params=req.params,
            tools=req.tools,
            tool_choice=req.tool_choice,
            extra_body=req.extra_body,
            index_version=self._cache_ver,
        )
        if key is None:
            self._metrics.cache_lookups.labels("bypass").inc()
        return key

    async def _cache_get(self, key: str) -> CachedResponse | None:
        assert self._cache is not None
        try:
            hit = await self._cache.get(key)
        except Exception as exc:  # noqa: BLE001 - Redis lỗi = miss, không làm hỏng đường chính
            log.warning("cache get failed", extra={"fields": {"error": type(exc).__name__}})
            self._metrics.cache_lookups.labels("error").inc()
            return None
        self._metrics.cache_lookups.labels("hit" if hit else "miss").inc()
        return hit

    async def _cache_put(
        self,
        key: str,
        *,
        text: str,
        finish_reason: str | None,
        has_tool_call: bool,
        usage: Usage,
        provider: str,
        model: str,
    ) -> None:
        """Chỉ ghi câu trả lời văn bản kết thúc `stop`; lỗi cache không ảnh hưởng response."""
        assert self._cache is not None
        if finish_reason != "stop" or has_tool_call or not text:
            self._metrics.cache_stores.labels("skipped").inc()
            return
        value = CachedResponse(
            content=text,
            finish_reason="stop",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            provider=provider,
            model=model,
        )
        try:
            await self._cache.put(key, value, self._cache_ttl_s)
        except Exception as exc:  # noqa: BLE001
            log.warning("cache put failed", extra={"fields": {"error": type(exc).__name__}})
            self._metrics.cache_stores.labels("error").inc()
            return
        self._metrics.cache_stores.labels("ok").inc()

    # ---------- non-stream ----------

    async def complete(self, request_id: str, caller: Caller, parsed: ParsedChat) -> ChatResult:
        t0 = self._clock.monotonic()
        resolved, provider, req = self._prepare(caller, parsed)
        key = self._cache_key(caller, parsed, provider, req)
        if key is not None and (hit := await self._cache_get(key)) is not None:
            return self._complete_hit(request_id, caller, parsed, resolved, hit, t0)
        cache_state = self._miss_state(key)
        t_call = self._clock.monotonic()
        sp = _chat_span(req.model)
        try:
            resp = await provider.complete(req)
        except ProviderError as exc:
            _end_chat_span(sp, None, None, exc.kind)
            self._provider_failed(request_id, caller, resolved, provider, req, exc, t0, t_call)
            raise GatewayError("all_providers_failed") from None
        except BaseException as exc:
            _end_chat_span(sp, None, None, type(exc).__name__)
            raise
        _end_chat_span(sp, resp.usage, resp.finish_reason)
        if key is not None:
            await self._cache_put(
                key,
                text=resp.message.get("content") or "",
                finish_reason=resp.finish_reason,
                has_tool_call=bool(resp.message.get("tool_calls")),
                usage=resp.usage,
                provider=provider.name,
                model=req.model,
            )
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
            self._headers(request_id, provider.name, req.model, parsed, cache_state),
        )

    def _miss_state(self, key: str | None) -> str | None:
        if self._cache is None:
            return None
        return "miss" if key is not None else "bypass"

    def _complete_hit(
        self,
        request_id: str,
        caller: Caller,
        parsed: ParsedChat,
        resolved: Resolved,
        hit: CachedResponse,
        t0: float,
    ) -> ChatResult:
        resp = ChatResponse(
            message={"role": "assistant", "content": hit.content},
            finish_reason=hit.finish_reason,
            usage=Usage(prompt_tokens=hit.prompt_tokens, completion_tokens=hit.completion_tokens),
            model=hit.model,
            provider=hit.provider,
        )
        _end_chat_span(_chat_span(hit.model, "exact"), None, hit.finish_reason)
        self._emit_hit(request_id, caller, parsed, resolved, hit, t0, None)
        created = int(self._clock.now().timestamp())
        return ChatResult(
            completion_body(request_id, parsed.alias, created, resp),
            self._headers(request_id, hit.provider, hit.model, parsed, "exact"),
        )

    def _emit_hit(
        self,
        request_id: str,
        caller: Caller,
        parsed: ParsedChat,
        resolved: Resolved,
        hit: CachedResponse,
        t0: float,
        ttft_ms: int | None,
        status: int = 200,
        error_code: str | None = None,
    ) -> None:
        """Usage event của lượt trúng cache: không có token tính phí, chi phí 0."""
        total = self._ms(t0)
        self._emit(
            request_id=request_id,
            caller=caller,
            resolved=resolved,
            requested_alias=parsed.alias,
            provider=hit.provider,
            model=hit.model,
            usage=None,
            status=status,
            error_code=error_code,
            latency_ms=total,
            overhead_ms=total,
            ttft_ms=ttft_ms,
            cache="exact",
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
        key = self._cache_key(caller, parsed, provider, req)
        if key is not None and (hit := await self._cache_get(key)) is not None:
            return StreamResult(
                self._cached_stream(request_id, caller, parsed, resolved, hit, t0),
                self._headers(request_id, hit.provider, hit.model, parsed, "exact"),
            )
        cache_state = self._miss_state(key)
        t_call = self._clock.monotonic()
        it = provider.stream(req)
        sp = _chat_span(req.model)
        try:
            first = await anext(it)
        except (ProviderError, StopAsyncIteration) as exc:
            await it.aclose()
            err = exc if isinstance(exc, ProviderError) else ProviderError("protocol")
            _end_chat_span(sp, None, None, err.kind)
            self._provider_failed(request_id, caller, resolved, provider, req, err, t0, t_call)
            raise GatewayError("all_providers_failed") from None
        except BaseException as exc:
            await it.aclose()
            _end_chat_span(sp, None, None, type(exc).__name__)
            raise
        ttft = self._ms(t_call)
        return StreamResult(
            self._run_stream(
                request_id,
                caller,
                parsed,
                resolved,
                provider,
                req,
                it,
                first,
                t0,
                t_call,
                ttft,
                sp,
                key,
            ),
            self._headers(request_id, provider.name, req.model, parsed, cache_state),
        )

    async def _cached_stream(
        self,
        request_id: str,
        caller: Caller,
        parsed: ParsedChat,
        resolved: Resolved,
        hit: CachedResponse,
        t0: float,
    ) -> AsyncIterator[str]:
        """Phát lại nội dung đã lưu theo đúng định dạng chunk SSE (một chunk nội dung)."""
        sp = _chat_span(hit.model, "exact")
        enc = StreamEncoder(
            request_id, parsed.alias, int(self._clock.now().timestamp()), parsed.include_usage
        )
        usage = Usage(prompt_tokens=hit.prompt_tokens, completion_tokens=hit.completion_tokens)
        status, error_code = 200, None
        ttft = self._ms(t0)
        try:
            for ch in (
                ChatChunk(text=hit.content),
                ChatChunk(finish_reason=hit.finish_reason, usage=usage),
            ):
                for line in enc.encode(ch):
                    yield line
            x_acme = {
                "request_id": request_id,
                "cost_usd": 0.0,
                "fallbacks": 0,
                "provider": hit.provider,
                "model": hit.model,
                "cache": "exact",
            }
            for line in enc.finish(usage, x_acme):
                yield line
        except (asyncio.CancelledError, GeneratorExit):
            status, error_code = 499, "client_disconnected"
            raise
        finally:
            _end_chat_span(sp, None, hit.finish_reason, error_code)
            self._emit_hit(request_id, caller, parsed, resolved, hit, t0, ttft, status, error_code)

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
        sp: Any,
        key: str | None = None,
    ) -> AsyncIterator[str]:
        enc = StreamEncoder(
            request_id, parsed.alias, int(self._clock.now().timestamp()), parsed.include_usage
        )
        usage = Usage()
        status, error_code = 200, None
        finish: str | None = None
        text: list[str] = []
        has_tool_call = False
        try:
            chunk: Any = first
            while True:
                if chunk.usage is not None:
                    usage = chunk.usage
                finish = chunk.finish_reason or finish
                if chunk.text:
                    text.append(chunk.text)
                has_tool_call = has_tool_call or chunk.tool_call is not None
                for line in enc.encode(chunk):
                    yield line
                try:
                    chunk = await anext(it)
                except StopAsyncIteration:
                    break
            if key is not None:  # stream đọc hết, không lỗi: mới được ghi
                await self._cache_put(
                    key,
                    text="".join(text),
                    finish_reason=finish,
                    has_tool_call=has_tool_call,
                    usage=usage,
                    provider=provider.name,
                    model=req.model,
                )
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
            _end_chat_span(sp, usage, finish, error_code)
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
