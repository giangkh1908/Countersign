"""Wire format Anthropic Messages: `POST /v1/messages` (non-stream, SSE, tool_use)."""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import behavior as bh

SCOPE = "anthropic"
_ERR_TYPES = {
    401: "authentication_error",
    429: "rate_limit_error",
    500: "api_error",
    503: "overloaded_error",
    504: "api_error",
}


def _error(status: int, message: str) -> dict[str, Any]:
    return {
        "type": "error",
        "error": {"type": _ERR_TYPES.get(status, "api_error"), "message": message},
    }


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            parts.append(_text_of(block.get("content")))
    return "\n".join(parts)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _message(msg_id: str, model: str, reply: bh.Reply) -> dict[str, Any]:
    if reply.is_tool:
        content: list[dict[str, Any]] = [
            {
                "type": "tool_use",
                "id": reply.tool_id,
                "name": reply.tool_name,
                "input": json.loads(reply.text),
            }
        ]
        stop = "tool_use"
    else:
        content = [{"type": "text", "text": reply.text}]
        stop = "max_tokens" if reply.truncated else "end_turn"
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens},
    }


async def _stream(msg_id: str, model: str, reply: bh.Reply, plan: bh.Plan) -> AsyncIterator[str]:
    full = _message(msg_id, model, reply)
    start = dict(full, content=[], stop_reason=None)
    start["usage"] = {"input_tokens": reply.input_tokens, "output_tokens": 0}
    yield _sse("message_start", {"type": "message_start", "message": start})
    block = (
        {"type": "tool_use", "id": reply.tool_id, "name": reply.tool_name, "input": {}}
        if reply.is_tool
        else {"type": "text", "text": ""}
    )
    yield _sse(
        "content_block_start", {"type": "content_block_start", "index": 0, "content_block": block}
    )
    yield _sse("ping", {"type": "ping"})
    cut = plan.cut_at(len(reply.pieces))
    delta_type, key = (
        ("input_json_delta", "partial_json") if reply.is_tool else ("text_delta", "text")
    )
    async for piece in bh.paced(reply.pieces[:cut], plan):
        delta = {"type": delta_type, key: piece}
        yield _sse(
            "content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}
        )
    if cut is not None:
        return  # ngắt giữa chừng: không có message_delta / message_stop
    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    usage = {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens}
    delta = {"stop_reason": full["stop_reason"], "stop_sequence": None}
    yield _sse("message_delta", {"type": "message_delta", "delta": delta, "usage": usage})
    yield _sse("message_stop", {"type": "message_stop"})


def router(ctx: bh.Context) -> APIRouter:
    r = APIRouter()

    @r.post("/v1/messages")
    async def messages(request: Request) -> Response:
        if not bh.key_ok(request, ctx.settings):
            return JSONResponse(_error(401, "invalid x-api-key"), 401)
        body = await request.json()
        messages = body.get("messages") or []
        system = _text_of(body.get("system"))
        texts = [_text_of(m.get("content")) for m in messages]
        users = [_text_of(m.get("content")) for m in messages if m.get("role") == "user"]
        prompt = users[-1] if users else ""
        plan = ctx.plan(request, SCOPE, prompt)
        if (err := await bh.early_error(plan, _error)) is not None:
            return err
        tools = [t["name"] for t in body.get("tools") or [] if "name" in t]
        reply = bh.make_reply(
            plan,
            prompt,
            "\n".join([system, *texts]),
            tools,
            ctx.settings.mock_tool_prefix,
            body.get("max_tokens"),
        )
        model = body.get("model", "mock")
        msg_id = "msg_mock" + bh.digest(plan.seed, prompt)[:16]
        if body.get("stream"):
            return StreamingResponse(
                _stream(msg_id, model, reply, plan), media_type="text/event-stream"
            )
        await bh.wait_full(reply, plan)
        return JSONResponse(_message(msg_id, model, reply))

    return r
