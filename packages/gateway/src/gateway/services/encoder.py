"""Dựng response/chunk theo chuẩn OpenAI Chat Completions từ kiểu trung lập (01 §7.3-7.4)."""

from __future__ import annotations

import json
from typing import Any

from ..ports.types import ChatChunk, ChatResponse, Usage

CHUNK_OBJECT = "chat.completion.chunk"


def usage_obj(u: Usage) -> dict[str, Any]:
    out: dict[str, Any] = {
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "total_tokens": u.total_tokens,
    }
    if u.cached_tokens:
        out["prompt_tokens_details"] = {"cached_tokens": u.cached_tokens}
    return out


def completion_body(
    request_id: str, alias: str, created: int, resp: ChatResponse
) -> dict[str, Any]:
    message = dict(resp.message)
    message.setdefault("role", "assistant")
    message.setdefault("content", None)
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": created,
        "model": alias,  # model thật ở header x-acme-model
        "choices": [{"index": 0, "message": message, "finish_reason": resp.finish_reason}],
        "usage": usage_obj(resp.usage),
    }


def sse(obj: dict[str, Any] | str) -> str:
    return f"data: {obj if isinstance(obj, str) else json.dumps(obj, separators=(',', ':'))}\n\n"


class StreamEncoder:
    """Trạng thái một stream: chunk đầu mang role; usage chunk (nếu include_usage) đứng cuối."""

    def __init__(self, request_id: str, alias: str, created: int, include_usage: bool) -> None:
        self._id = f"chatcmpl-{request_id}"
        self._alias = alias
        self._created = created
        self._include_usage = include_usage
        self._started = False

    def _chunk(self, delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return {
            "id": self._id,
            "object": CHUNK_OBJECT,
            "created": self._created,
            "model": self._alias,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    def _role(self) -> list[str]:
        if self._started:
            return []
        self._started = True
        return [sse(self._chunk({"role": "assistant", "content": ""}))]

    def encode(self, ch: ChatChunk) -> list[str]:
        out = self._role()
        if ch.text:
            out.append(sse(self._chunk({"content": ch.text})))
        if ch.tool_call is not None:
            tc = ch.tool_call
            fn: dict[str, Any] = {"arguments": tc.arguments}
            entry: dict[str, Any] = {"index": tc.index, "function": fn}
            if tc.id is not None:
                entry["id"] = tc.id
                entry["type"] = "function"
            if tc.name is not None:
                fn["name"] = tc.name
            out.append(sse(self._chunk({"tool_calls": [entry]})))
        if ch.finish_reason:
            out.append(sse(self._chunk({}, ch.finish_reason)))
        return out

    def finish(self, usage: Usage, x_acme: dict[str, Any]) -> list[str]:
        out = self._role()
        if self._include_usage:
            final = self._chunk({})
            final["choices"] = []
            final["usage"] = usage_obj(usage)
            final["x_acme"] = x_acme
            out.append(sse(final))
        out.append(sse("[DONE]"))
        return out
