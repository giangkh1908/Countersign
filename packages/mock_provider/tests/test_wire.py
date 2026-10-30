"""Wire format 3 provider: non-stream + stream + tool calling, parse bằng httpx thuần."""

import json

import httpx
from mock_provider.behavior import count_tokens

A_BODY = {
    "model": "claude-x",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "hi there"}],
}
O_BODY = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi there"}]}
G_BODY = {"contents": [{"role": "user", "parts": [{"text": "hi there"}]}]}
G_URL = "/v1beta/models/gemini-x"


def sse_events(text: str) -> list[tuple[str | None, str]]:
    out = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        ev = None
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        out.append((ev, data))
    return out


async def test_anthropic_non_stream(http: httpx.AsyncClient) -> None:
    r = await http.post("/v1/messages", json=A_BODY)
    j = r.json()
    assert r.status_code == 200 and j["type"] == "message" and j["stop_reason"] == "end_turn"
    assert j["usage"] == {"input_tokens": 2, "output_tokens": 8}
    assert count_tokens(j["content"][0]["text"]) == 8


async def test_anthropic_stream(http: httpx.AsyncClient) -> None:
    r = await http.post("/v1/messages", json={**A_BODY, "stream": True})
    ev = sse_events(r.text)
    names = [e for e, _ in ev]
    assert names[0] == "message_start" and names[-1] == "message_stop"
    assert names[-2] == "message_delta" and names.count("content_block_delta") == 8
    delta = json.loads(ev[-2][1])
    assert delta["usage"]["output_tokens"] == 8
    text = "".join(json.loads(d)["delta"]["text"] for e, d in ev if e == "content_block_delta")
    assert text == (await http.post("/v1/messages", json=A_BODY)).json()["content"][0]["text"]


async def test_anthropic_tool_use(http: httpx.AsyncClient) -> None:
    body = {
        **A_BODY,
        "messages": [{"role": "user", "content": 'call_tool:get_weather {"city":"Hue"}'}],
        "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
    }
    j = (await http.post("/v1/messages", json=body)).json()
    assert j["stop_reason"] == "tool_use"
    assert j["content"][0]["name"] == "get_weather" and j["content"][0]["input"] == {"city": "Hue"}
    r = await http.post("/v1/messages", json={**body, "stream": True})
    ev = sse_events(r.text)
    start = json.loads(next(d for e, d in ev if e == "content_block_start"))
    assert start["content_block"]["type"] == "tool_use"
    args = "".join(
        json.loads(d)["delta"]["partial_json"] for e, d in ev if e == "content_block_delta"
    )
    assert json.loads(args) == {"city": "Hue"}
    assert json.loads(ev[-2][1])["delta"]["stop_reason"] == "tool_use"


async def test_openai_non_stream(http: httpx.AsyncClient) -> None:
    j = (await http.post("/v1/chat/completions", json=O_BODY)).json()
    assert j["object"] == "chat.completion" and j["choices"][0]["finish_reason"] == "stop"
    assert j["usage"] == {"prompt_tokens": 2, "completion_tokens": 8, "total_tokens": 10}


async def test_openai_stream_usage(http: httpx.AsyncClient) -> None:
    body = {**O_BODY, "stream": True, "stream_options": {"include_usage": True}}
    lines = [
        x for x in (await http.post("/v1/chat/completions", json=body)).text.split("\n\n") if x
    ]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(x[6:]) for x in lines[:-1]]
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"]["completion_tokens"] == 8
    assert chunks[-2]["choices"][0]["finish_reason"] == "stop"
    # không include_usage -> không có chunk usage
    plain = (await http.post("/v1/chat/completions", json={**O_BODY, "stream": True})).text
    assert '"usage"' not in plain


async def test_openai_tool_calls(http: httpx.AsyncClient) -> None:
    tool = {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}
    body = {
        **O_BODY,
        "messages": [{"role": "user", "content": 'call_tool:lookup {"q":"a b"}'}],
        "tools": [tool],
    }
    c = (await http.post("/v1/chat/completions", json=body)).json()["choices"][0]
    assert c["finish_reason"] == "tool_calls"
    assert json.loads(c["message"]["tool_calls"][0]["function"]["arguments"]) == {"q": "a b"}
    text = (await http.post("/v1/chat/completions", json={**body, "stream": True})).text
    chunks = [json.loads(x[6:]) for x in text.split("\n\n") if x.startswith("data: {")]
    calls = [
        c["choices"][0]["delta"]["tool_calls"][0]
        for c in chunks
        if c["choices"][0]["delta"].get("tool_calls")
    ]
    assert calls[0]["function"]["name"] == "lookup"
    assert json.loads("".join(c["function"]["arguments"] for c in calls)) == {"q": "a b"}


async def test_gemini_non_stream(http: httpx.AsyncClient) -> None:
    j = (await http.post(f"{G_URL}:generateContent", json=G_BODY)).json()
    assert j["candidates"][0]["finishReason"] == "STOP"
    assert j["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 8,
        "totalTokenCount": 10,
    }


async def test_gemini_stream_and_tool(http: httpx.AsyncClient) -> None:
    r = await http.post(f"{G_URL}:streamGenerateContent?alt=sse", json=G_BODY)
    chunks = [json.loads(d) for _, d in sse_events(r.text)]
    assert chunks[-1]["usageMetadata"]["candidatesTokenCount"] == 8
    assert chunks[-1]["candidates"][0]["finishReason"] == "STOP"
    body = {
        "contents": [{"role": "user", "parts": [{"text": 'call_tool:search {"k":1}'}]}],
        "tools": [{"functionDeclarations": [{"name": "search"}]}],
    }
    j = (await http.post(f"{G_URL}:generateContent", json=body)).json()
    assert j["candidates"][0]["content"]["parts"][0]["functionCall"] == {
        "name": "search",
        "args": {"k": 1},
    }


async def test_max_tokens_truncates(http: httpx.AsyncClient) -> None:
    j = (await http.post("/v1/messages", json={**A_BODY, "max_tokens": 3})).json()
    assert j["stop_reason"] == "max_tokens" and j["usage"]["output_tokens"] == 3


async def test_echo_prompt(http: httpx.AsyncClient) -> None:
    body = {**O_BODY, "messages": [{"role": "user", "content": "echo: xin chào, thế giới"}]}
    j = (await http.post("/v1/chat/completions", json=body)).json()
    assert j["choices"][0]["message"]["content"] == "xin chào, thế giới"
    assert j["usage"]["completion_tokens"] == count_tokens("xin chào, thế giới")
