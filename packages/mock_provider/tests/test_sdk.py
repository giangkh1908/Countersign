"""Dùng SDK thật (openai, anthropic) trỏ base_url vào app qua ASGI, offline."""

import anthropic
import httpx
import httpx2
import openai


async def test_openai_sdk(app) -> None:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    client = openai.AsyncOpenAI(
        base_url="http://mock/v1", api_key="any", http_client=http, max_retries=0
    )
    msgs = [{"role": "user", "content": "hello"}]
    r = await client.chat.completions.create(model="gpt-x", messages=msgs)
    assert r.usage and r.usage.completion_tokens == 8 and r.choices[0].message.content

    stream = await client.chat.completions.create(
        model="gpt-x", messages=msgs, stream=True, stream_options={"include_usage": True}
    )
    text, usage = "", None
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            text += chunk.choices[0].delta.content
        if chunk.usage:
            usage = chunk.usage
    assert text == r.choices[0].message.content
    assert usage and usage.completion_tokens == 8


# anthropic SDK dùng httpx2 (phụ thuộc bắc cầu của chính SDK) thay vì httpx.
async def test_anthropic_sdk(app) -> None:
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
    client = anthropic.AsyncAnthropic(
        base_url="http://mock", api_key="any", http_client=http, max_retries=0
    )
    msgs = [{"role": "user", "content": "hello"}]
    r = await client.messages.create(model="claude-x", max_tokens=50, messages=msgs)
    assert r.usage.output_tokens == 8 and r.content[0].type == "text"

    async with client.messages.stream(model="claude-x", max_tokens=50, messages=msgs) as s:
        final = await s.get_final_message()
    assert final.content[0].text == r.content[0].text
    assert final.usage.output_tokens == 8 and final.stop_reason == "end_turn"

    tool_msgs = [{"role": "user", "content": 'call_tool:ping {"n":2}'}]
    tools = [{"name": "ping", "description": "p", "input_schema": {"type": "object"}}]
    t = await client.messages.create(
        model="claude-x", max_tokens=50, messages=tool_msgs, tools=tools
    )
    assert t.stop_reason == "tool_use" and t.content[0].input == {"n": 2}


async def test_openai_sdk_errors(app) -> None:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    client = openai.AsyncOpenAI(
        base_url="http://mock/v1", api_key="any", http_client=http, max_retries=0
    )
    try:
        await client.chat.completions.create(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            extra_headers={"x-mock-error": "429", "x-mock-retry-after-s": "7"},
        )
    except openai.RateLimitError as e:
        assert e.response.headers["retry-after"] == "7"
    else:
        raise AssertionError("expected RateLimitError")
