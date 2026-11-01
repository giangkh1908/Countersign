"""Wire format Gemini: `:generateContent` và `:streamGenerateContent?alt=sse`."""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import behavior as bh

SCOPE = "gemini"
_STATUS = {
    401: "UNAUTHENTICATED",
    429: "RESOURCE_EXHAUSTED",
    500: "INTERNAL",
    503: "UNAVAILABLE",
    504: "DEADLINE_EXCEEDED",
}


def _error(status: int, message: str) -> dict[str, Any]:
    return {"error": {"code": status, "message": message, "status": _STATUS.get(status, "UNKNOWN")}}


def _text_of(content: dict[str, Any] | None) -> str:
    out: list[str] = []
    for part in (content or {}).get("parts") or []:
        if "text" in part:
            out.append(part["text"])
        elif "functionResponse" in part:
            out.append(json.dumps(part["functionResponse"].get("response", {})))
    return "\n".join(out)


def _usage(reply: bh.Reply) -> dict[str, int]:
    n_out = reply.output_tokens
    return {
        "promptTokenCount": reply.input_tokens,
        "candidatesTokenCount": n_out,
        "totalTokenCount": reply.input_tokens + n_out,
    }


def _finish(reply: bh.Reply) -> str:
    return "MAX_TOKENS" if reply.truncated else "STOP"


def _response(
    model: str, parts: list[dict[str, Any]], reply: bh.Reply, final: bool
) -> dict[str, Any]:
    cand: dict[str, Any] = {"content": {"role": "model", "parts": parts}, "index": 0}
    out: dict[str, Any] = {"candidates": [cand], "modelVersion": model}
    if final:
        cand["finishReason"] = _finish(reply)
        out["usageMetadata"] = _usage(reply)
    return out


def _all_parts(reply: bh.Reply) -> list[dict[str, Any]]:
    if reply.is_tool:
        return [{"functionCall": {"name": reply.tool_name, "args": json.loads(reply.text)}}]
    return [{"text": reply.text}]


async def _stream(model: str, reply: bh.Reply, plan: bh.Plan) -> AsyncIterator[str]:
    def sse(obj: dict[str, Any]) -> str:
        return f"data: {json.dumps(obj, separators=(',', ':'))}\r\n\r\n"

    # Tool call đi trong một chunk; text đi theo từng piece.
    pieces = [""] if reply.is_tool else reply.pieces
    cut = plan.cut_at(len(pieces))
    async for piece in bh.paced(pieces[:cut], plan):
        parts = _all_parts(reply) if reply.is_tool else [{"text": piece}]
        yield sse(_response(model, parts, reply, final=False))
    if cut is None:  # chunk cuối mang finishReason + usage
        yield sse(_response(model, [{"text": ""}], reply, final=True))


def router(ctx: bh.Context) -> APIRouter:
    r = APIRouter()

    @r.post("/v1beta/models/{spec}")
    async def generate(spec: str, request: Request) -> Response:
        model, _, action = spec.rpartition(":")
        if action not in ("generateContent", "streamGenerateContent"):
            return JSONResponse(_error(404, f"unsupported method {action}"), 404)
        if not bh.key_ok(request, ctx.settings):
            return JSONResponse(_error(401, "API key not valid"), 401)
        body = await request.json()
        contents = body.get("contents") or []
        system = _text_of(body.get("systemInstruction"))
        users = [_text_of(c) for c in contents if c.get("role", "user") == "user"]
        prompt = users[-1] if users else ""
        plan = ctx.plan(request, SCOPE, prompt)
        if (err := await bh.early_error(plan, _error)) is not None:
            return err
        tools = [
            d["name"] for t in body.get("tools") or [] for d in t.get("functionDeclarations") or []
        ]
        max_tokens = (body.get("generationConfig") or {}).get("maxOutputTokens")
        reply = bh.make_reply(
            plan,
            prompt,
            "\n".join([system, *(_text_of(c) for c in contents)]),
            tools,
            ctx.settings.mock_tool_prefix,
            max_tokens,
        )
        if action == "streamGenerateContent":
            return StreamingResponse(_stream(model, reply, plan), media_type="text/event-stream")
        await bh.wait_full(reply, plan)
        return JSONResponse(_response(model, _all_parts(reply), reply, final=True))

    return r
