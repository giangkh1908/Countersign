"""Adapter `anthropic` cho port `ChatProvider`. Chỉ file này import SDK Anthropic.

Làm đúng 3 việc (01 §7): dịch `ChatRequest` -> tham số Messages API; parse response/SSE -> `ChatResponse`/`ChatChunk`;
ánh xạ lỗi -> `ProviderError`. Message lỗi không chứa URL, header, key hay nội dung. Không retry (M2: decorator).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from ..ports.chat_provider import ChatProvider
from ..ports.types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    ProviderError,
    ToolCallDelta,
    Usage,
)

FALLBACK_MAX_TOKENS = 4096  # chỉ khi service không điền params["max_tokens"]
_STOP_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
    "pause_turn": "stop",
    "model_context_window_exceeded": "length",
}


# ---------- OpenAI -> Messages API ----------


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        p.get("text", "") for p in content or [] if isinstance(p, dict) and p.get("type") == "text"
    )


def _image_block(url: str) -> dict[str, Any]:
    if url.startswith("data:") and ";base64," in url:
        head, _, data = url.partition(";base64,")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": head[5:], "data": data},
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _blocks(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    out: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            out.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url:
                out.append(_image_block(url))
    return out


def _parse_args(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except ValueError:
        return {}
    return val if isinstance(val, dict) else {}


def _convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    system: list[str] = []
    out: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:  # gộp message liên tiếp cùng role
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m.get("role")
        if role in ("system", "developer"):
            text = _text_of(m.get("content"))
            if text:
                system.append(text)
        elif role == "user":
            push("user", _blocks(m.get("content")))
        elif role == "assistant":
            blocks = _blocks(m.get("content"))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": _parse_args(fn.get("arguments")),
                    }
                )
            push("assistant", blocks)  # rỗng thì bỏ (Anthropic từ chối content rỗng)
        elif role == "tool":
            push(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", ""),
                        "content": _text_of(m.get("content")),
                    }
                ],
            )
    return ("\n\n".join(system) or None), out


def _convert_tools(
    req: ChatRequest,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    choice = req.tool_choice
    if not req.tools or choice == "none":
        return None, None
    tools = []
    for t in req.tools:
        fn = t.get("function") or {}
        tools.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    tc: dict[str, Any] | None
    if choice == "required":
        tc = {"type": "any"}
    elif isinstance(choice, dict) and (choice.get("function") or {}).get("name"):
        tc = {"type": "tool", "name": choice["function"]["name"]}
    else:
        tc = {"type": "auto"}
    if req.params.get("parallel_tool_calls") is False:
        tc["disable_parallel_tool_use"] = True
    return tools, tc


def build_params(req: ChatRequest) -> dict[str, Any]:
    system, messages = _convert_messages(req.messages)
    p = req.params
    kwargs: dict[str, Any] = {
        "model": req.model,
        "messages": messages,
        "max_tokens": p.get("max_tokens") or FALLBACK_MAX_TOKENS,
    }
    if system:
        kwargs["system"] = system
    if p.get("temperature") is not None:
        kwargs["temperature"] = min(float(p["temperature"]), 1.0)
    if p.get("top_p") is not None:
        kwargs["top_p"] = p["top_p"]
    stop = p.get("stop")
    if stop:
        kwargs["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
    tools, tool_choice = _convert_tools(req)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice
    return kwargs


# ---------- Messages API -> neutral ----------


def _usage(u: Any) -> Usage:
    inp = int(getattr(u, "input_tokens", 0) or 0)
    read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    return Usage(
        prompt_tokens=inp + read + write,  # input_tokens của vendor KHÔNG gồm cache
        completion_tokens=int(getattr(u, "output_tokens", 0) or 0),
        cached_tokens=read,
        cache_write_tokens=write,
    )


def _map_error(exc: Exception) -> ProviderError:
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("timeout", retryable=True)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("connection", retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        code = exc.status_code
        retry_after: float | None
        try:
            retry_after = float(exc.response.headers.get("retry-after", ""))
        except ValueError:
            retry_after = None
        return ProviderError(
            f"http_{code}",
            retryable=code in (408, 409, 429) or code >= 500,
            retry_after_s=retry_after,
        )
    return ProviderError("protocol")


class AnthropicChatProvider(ChatProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout_s: float = 60.0,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0
        )

    async def complete(self, req: ChatRequest) -> ChatResponse:
        try:
            msg = await self._client.messages.create(**build_params(req))
        except anthropic.AnthropicError as exc:
            raise _map_error(exc) from None
        text = "".join(b.text for b in msg.content if b.type == "text")
        calls = [
            {
                "id": b.id,
                "type": "function",
                "function": {"name": b.name, "arguments": json.dumps(b.input)},
            }
            for b in msg.content
            if b.type == "tool_use"
        ]
        message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = calls
        return ChatResponse(
            message=message,
            finish_reason=_STOP_MAP.get(msg.stop_reason or "end_turn", "stop"),
            usage=_usage(msg.usage),
            model=msg.model,
            provider=self.name,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        usage = Usage()
        tool_index = -1
        finished = False
        try:
            events = await self._client.messages.create(**build_params(req), stream=True)
            async for ev in events:
                t = ev.type
                if t == "message_start":
                    usage = _usage(ev.message.usage)
                elif t == "content_block_start" and ev.content_block.type == "tool_use":
                    tool_index += 1
                    yield ChatChunk(
                        tool_call=ToolCallDelta(
                            index=tool_index, id=ev.content_block.id, name=ev.content_block.name
                        )
                    )
                elif t == "content_block_delta":
                    d = ev.delta
                    if d.type == "text_delta":
                        yield ChatChunk(text=d.text)
                    elif d.type == "input_json_delta":
                        yield ChatChunk(
                            tool_call=ToolCallDelta(index=tool_index, arguments=d.partial_json)
                        )
                    # thinking_delta / signature_delta: bỏ
                elif t == "message_delta":
                    usage.completion_tokens = max(
                        usage.completion_tokens, int(ev.usage.output_tokens or 0)
                    )
                    reason = ev.delta.stop_reason
                    if reason:
                        finished = True
                        yield ChatChunk(finish_reason=_STOP_MAP.get(reason, "stop"))
                elif t == "message_stop":
                    yield ChatChunk(usage=usage)
        except anthropic.AnthropicError as exc:
            raise _map_error(exc) from None
        if not finished:  # stream bị cắt trước message_delta
            raise ProviderError("protocol", retryable=True)

    async def aclose(self) -> None:
        await self._client.close()
