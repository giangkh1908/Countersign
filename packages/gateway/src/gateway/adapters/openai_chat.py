"""Adapter chung cho port `ChatProvider` qua wire OpenAI-compatible (`mock-provider`, OpenRouter...).

Dùng với `GW_PROVIDER_OVERRIDE=mock` hoặc chain `openrouter/<model>`; có `api_key` thì gửi Bearer. Không retry. Message lỗi không chứa URL.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..ports.chat_provider import ChatProvider
from ..ports.types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    ProviderError,
    ToolCallDelta,
    Usage,
)

_PASS_PARAMS = ("temperature", "top_p", "max_tokens", "stop", "parallel_tool_calls")


def _usage(u: dict[str, Any] | None) -> Usage:
    u = u or {}
    details = u.get("prompt_tokens_details") or {}
    return Usage(
        prompt_tokens=int(u.get("prompt_tokens") or 0),
        completion_tokens=int(u.get("completion_tokens") or 0),
        cached_tokens=int(details.get("cached_tokens") or 0),
    )


def _status_error(resp: httpx.Response) -> ProviderError:
    retry_after: float | None
    try:
        retry_after = float(resp.headers.get("retry-after", ""))
    except ValueError:
        retry_after = None
    code = resp.status_code
    return ProviderError(
        f"http_{code}", retryable=code in (408, 429) or code >= 500, retry_after_s=retry_after
    )


class OpenAIChatProvider(ChatProvider):
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 60.0,
        api_key: str | None = None,
        name: str = "openai_chat",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers=headers,
            trust_env=False,
            follow_redirects=False,
        )

    def _body(self, req: ChatRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"model": req.model, "messages": req.messages, "stream": req.stream}
        for k in _PASS_PARAMS:
            if req.params.get(k) is not None:
                body[k] = req.params[k]
        if req.tools:
            body["tools"] = req.tools
            if req.tool_choice is not None:
                body["tool_choice"] = req.tool_choice
        if req.stream:
            body["stream_options"] = {"include_usage": True}
        return body

    async def complete(self, req: ChatRequest) -> ChatResponse:
        try:
            resp = await self._client.post("/v1/chat/completions", json=self._body(req))
        except httpx.TimeoutException:
            raise ProviderError("timeout", retryable=True) from None
        except httpx.TransportError:
            raise ProviderError("connection", retryable=True) from None
        if resp.status_code != 200:
            raise _status_error(resp)
        try:
            data = resp.json()
            choice = data["choices"][0]
            message = dict(choice["message"])
            return ChatResponse(
                message=message,
                finish_reason=choice.get("finish_reason") or "stop",
                usage=_usage(data.get("usage")),
                model=str(data.get("model", req.model)),
                provider=self.name,
            )
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("protocol") from None

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        try:
            async with self._client.stream(
                "POST", "/v1/chat/completions", json=self._body(req)
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise _status_error(resp)
                done = False
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        done = True
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        raise ProviderError("protocol") from None
                    for out in self._chunks(chunk):
                        yield out
                if not done:  # stream bị cắt giữa chừng
                    raise ProviderError("protocol", retryable=True)
        except httpx.TimeoutException:
            raise ProviderError("timeout", retryable=True) from None
        except httpx.TransportError:
            raise ProviderError("connection", retryable=True) from None

    @staticmethod
    def _chunks(chunk: dict[str, Any]) -> list[ChatChunk]:
        out: list[ChatChunk] = []
        if chunk.get("usage"):
            out.append(ChatChunk(usage=_usage(chunk["usage"])))
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                out.append(ChatChunk(text=delta["content"]))
            for tc in delta.get("tool_calls") or []:
                fn = tc.get("function") or {}
                out.append(
                    ChatChunk(
                        tool_call=ToolCallDelta(
                            index=int(tc.get("index", 0)),
                            id=tc.get("id"),
                            name=fn.get("name"),
                            arguments=fn.get("arguments") or "",
                        )
                    )
                )
            if choice.get("finish_reason"):
                out.append(ChatChunk(finish_reason=choice["finish_reason"]))
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
