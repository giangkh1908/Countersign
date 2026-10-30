from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from agent.main import create_app
from agent.testing import AUTH, TOKEN, FakeToolProvider, build_test_container, parse_sse
from langchain_core.messages import AIMessage


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)  # CommonSettings đọc .env theo đường dẫn tương đối
    monkeypatch.setenv("ACME_ENV", "test")


class Env:
    def __init__(
        self, container: Any, provider: FakeToolProvider, client: httpx.AsyncClient
    ) -> None:
        self.c, self.provider, self.client = container, provider, client

    async def new_thread(self) -> str:
        r = await self.client.post("/v1/threads", json={}, headers=AUTH)
        assert r.status_code == 201
        return r.json()["thread_id"]

    async def run(
        self, tid: str, text: str, msg_id: str = "m1"
    ) -> list[tuple[str, dict[str, Any]]]:
        r = await self.client.post(
            f"/v1/threads/{tid}/runs",
            json={"input": {"text": text}, "client_msg_id": msg_id},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        return parse_sse(r.text)

    async def resume(
        self, tid: str, interrupt_id: str, decision: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        r = await self.client.post(
            f"/v1/threads/{tid}/resume",
            json={"interrupt_id": interrupt_id, "decision": decision},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        return parse_sse(r.text)


@pytest_asyncio.fixture
async def make_env() -> AsyncIterator[Any]:
    clients: list[httpx.AsyncClient] = []

    def make(provider: FakeToolProvider, scripts: dict[str, list[AIMessage]]) -> Env:
        container = build_test_container(provider, scripts, token=TOKEN)
        app = create_app(container.settings, container)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")
        clients.append(client)
        return Env(container, provider, client)

    yield make
    for c in clients:
        await c.aclose()
