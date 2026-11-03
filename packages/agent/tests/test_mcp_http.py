"""McpHttpToolProvider chạy thật qua SDK `mcp`, server MCP in-process (ASGI), không mạng."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from acme_common.testing import FakeClock, FakeTokenBroker
from agent.adapters.mcp_http import MAX_OUTPUT_BYTES, McpHttpToolProvider, fit_output
from agent.factory import build_agent_registry
from agent.settings import Settings
from agent.testing import make_principal
from mcp.server.mcpserver import MCPServer

SEEN: list[dict[str, Any]] = []


def make_server() -> MCPServer:
    srv = MCPServer("tickets-test")

    @srv.tool()
    def get_ticket(code: str) -> dict[str, Any]:
        """Lay ticket."""
        if code == "big":
            return {"results": [{"text": "x" * 4000} for _ in range(20)]}
        return {"code": code, "status": "open"}

    @srv.tool()
    def prepare_close_ticket(code: str, resolution: str) -> dict[str, Any]:
        """Chuan bi dong ticket."""
        return {
            "ok": True,
            "intent_id": "i1",
            "intent_jws": "j",
            "expires_at": "2099-01-01T00:00:00Z",
        }

    @srv.tool()
    def prepare_create_ticket(title: str, body: str) -> dict[str, Any]:
        """Chuan bi tao ticket (intent_jws dai, khong duoc cat)."""
        return {"ok": True, "intent_id": "i2", "intent_jws": "j" * 20000, "expires_at": "x"}

    @srv.tool()
    def commit_intent(intent_id: str, approval_token: str) -> dict[str, Any]:
        """Commit."""
        SEEN.append({"intent_id": intent_id, "approval_token": approval_token})
        if approval_token == "bad":
            raise ValueError("intent_expired")
        return {"op": "close_ticket", "event_id": "e1", "ticket": {"code": "TCK-000123"}}

    return srv


@asynccontextmanager
async def open_provider() -> Any:
    srv = make_server()
    app = srv.streamable_http_app()
    SEEN.clear()
    async with app.router.lifespan_context(app):

        def factory(headers: dict[str, str]) -> httpx2.AsyncClient:
            return httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
                headers=headers,
            )

        s = Settings(acme_env="test")
        reg = build_agent_registry(s)
        broker = FakeTokenBroker(FakeClock())
        yield (
            McpHttpToolProvider(
                {
                    "tickets-mcp": "http://127.0.0.1:8000/mcp",
                    "docs-mcp": "http://127.0.0.1:8000/mcp",
                },
                broker,
                reg.access_map(),
                http_client_factory=factory,
            ),
            broker,
        )


async def test_tools_filtered_by_allowlist_and_callable() -> None:
    async with open_provider() as (prov, broker):
        tools = await prov.tools_for("ticket_agent", make_principal(), "ut", thread_id="t-1")
        names = {t.name for t in tools}
        assert names == {
            "get_ticket",
            "prepare_close_ticket",
            "prepare_create_ticket",
        }  # commit_intent không lộ cho LLM
        t = next(t for t in tools if t.name == "get_ticket")
        assert "TCK-000123" in await t.ainvoke({"code": "TCK-000123"})
        assert ("u1", "tickets-mcp", ("tickets:read",)) in broker.calls


async def test_prepare_create_ticket_output_not_truncated() -> None:
    async with open_provider() as (prov, _):
        tools = await prov.tools_for("ticket_agent", make_principal(), "ut", thread_id="t-1")
        t = next(t for t in tools if t.name == "prepare_create_ticket")
        out = await t.ainvoke({"title": "abc", "body": "abc"})
        assert json.loads(out)["intent_jws"] == "j" * 20000  # JSON nguyên vẹn, không bị cắt


async def test_commit_sends_only_two_args() -> None:
    async with open_provider() as (prov, _):
        res = await prov.commit_intent(
            "ticket_agent", "i1", "tok", principal=make_principal(), user_token="ut"
        )
        assert res["ok"] is True and res["ticket"]["code"] == "TCK-000123"
        assert SEEN == [{"intent_id": "i1", "approval_token": "tok"}]


async def test_commit_business_error_is_mapped() -> None:
    async with open_provider() as (prov, _):
        res = await prov.commit_intent(
            "ticket_agent", "i1", "bad", principal=make_principal(), user_token="ut"
        )
        assert res["ok"] is False
        assert isinstance(res["error"]["code"], str)


async def test_large_result_stays_valid_json_with_results() -> None:
    async with open_provider() as (prov, _):
        tools = await prov.tools_for("ticket_agent", make_principal(), "ut", thread_id="t-1")
        t = next(t for t in tools if t.name == "get_ticket")
        out = await t.ainvoke({"code": "big"})
        data = json.loads(out)
        assert data["results"] and data["truncated"] is True and data["omitted"] > 0
        assert len(out.encode()) <= MAX_OUTPUT_BYTES


def test_fit_output_small_unchanged_and_no_truncate_exempt() -> None:
    small = {"results": [1, 2]}
    assert json.loads(fit_output("search_documents", small)) == small
    big = {"intent_jws": "j" * 50000}
    assert json.loads(fit_output("prepare_create_ticket", big)) == big


def test_fit_output_untruncatable_returns_valid_json() -> None:
    out2 = json.loads(fit_output("x", ["a" * 40000]))
    assert out2 == {"truncated": True, "error": {"code": "output_too_large"}}
