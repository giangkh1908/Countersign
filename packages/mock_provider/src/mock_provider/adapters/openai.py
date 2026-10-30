"""Wire format OpenAI-compatible: `POST /v1/chat/completions` (non-stream, SSE, tool_calls)."""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import behavior as bh

SCOPE = "openai"
_ERR_TYPES = {
    401: ("invalid_request_error", "invalid_api_key"),
    429: ("rate_limit_error", "rate_limit_exceeded"),
    500: ("server_error", "internal_error"),
    503: ("server_error", "service_unavailable"),
    504: ("server_error", "timeout"),
}


def _error(status: int, message: str) -> dict[str, Any]:
    etype, code = _ERR_TYPES.get(status, ("server_error", None))
    return {"error": {"message": message, "type": etype, "param": None, "code": code}}


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content or [] if p.get("type") == "text")


def _usage(reply: bh.Reply) -> dict[str, int]:
    n_out = reply.output_tokens
    return {
        "prompt_tokens": reply.input_tokens,
        "completion_tokens": n_out,
        "total_tokens": reply.input_tokens + n_out,
    }


def _finish(reply: bh.Reply) -> str:
    return "tool_calls" if reply.is_tool else ("length" if reply.truncated else "stop")


def _call(reply: bh.Reply, arguments: str, index: int | None = None) -> dict[str, Any]:
    call: dict[str, Any] = {
        "id": reply.tool_id,
        "type": "function",
        "function": {"name": reply.tool_name, "arguments": arguments},
    }
    if index is not None:
        call["index"] = index
    return call


def _completion(cid: str, model: str, reply: bh.Reply) -> dict[str, Any]:
    if reply.is_tool:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [_call(reply, reply.text)],
        }
    else:
        message = {"role": "assistant", "content": reply.text}
    return {
        "id": cid,
        "object": "chat.completion",
        "created": bh.CREATED,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": _finish(reply)}],
        "usage": _usage(reply),
    }


def _chunk(
    cid: str, model: str, delta: dict[str, Any], finish: str | None = None
) -> dict[str, Any]:
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": bh.CREATED,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _data(obj: dict[str, Any] | str) -> str:
    return f"data: {obj if isinstance(obj, str) else json.dumps(obj, separators=(',', ':'))}\n\n"


async def _stream(
    cid: str, model: str, reply: bh.Reply, plan: bh.Plan, include_usage: bool
) -> AsyncIterator[str]:
    yield _data(_chunk(cid, model, {"role": "assistant", "content": None if reply.is_tool else ""}))
    cut = plan.cut_at(len(reply.pieces))
    first = True
    async for piece in bh.paced(reply.pieces[:cut], plan):
        if reply.is_tool:
            call = (
                _call(reply, piece, 0) if first else {"index": 0, "function": {"arguments": piece}}
            )
            delta: dict[str, Any] = {"tool_calls": [call]}
        else:
            delta = {"content": piece}
        first = False
        yield _data(_chunk(cid, model, delta))
    if cut is not None:
        return  # ngắt giữa chừng: không có finish_reason / [DONE]
    yield _data(_chunk(cid, model, {}, _finish(reply)))
    if include_usage:
        final = _chunk(cid, model, {})
        final["choices"] = []
        final["usage"] = _usage(reply)
        yield _data(final)
    yield _data("[DONE]")


def router(ctx: bh.Context) -> APIRouter:
    r = APIRouter()

    @r.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        if not bh.key_ok(request, ctx.settings):
            return JSONResponse(_error(401, "Incorrect API key provided"), 401)
        body = await request.json()
        messages = body.get("messages") or []
        texts = [_text_of(m.get("content")) for m in messages]
        users = [_text_of(m.get("content")) for m in messages if m.get("role") == "user"]
        prompt = users[-1] if users else ""
        plan = ctx.plan(request, SCOPE, prompt)
        if (err := await bh.early_error(plan, _error)) is not None:
            return err
        tools = [t["function"]["name"] for t in body.get("tools") or [] if "function" in t]
        max_tokens = body.get("max_completion_tokens") or body.get("max_tokens")
        joined = "\n".join(texts)
        reply = ctx.scripted_reply(joined, tools) or bh.make_reply(
            plan, prompt, joined, tools, ctx.settings.mock_tool_prefix, max_tokens
        )
        model = body.get("model", "mock")
        cid = "chatcmpl-mock" + bh.digest(plan.seed, prompt)[:16]
        if body.get("stream"):
            include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
            return StreamingResponse(
                _stream(cid, model, reply, plan, include_usage), media_type="text/event-stream"
            )
        await bh.wait_full(reply, plan)
        return JSONResponse(_completion(cid, model, reply))

    return r
