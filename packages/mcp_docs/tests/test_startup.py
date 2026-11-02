"""Khởi động docs-mcp: sai cấu hình chỉ mục thì lifespan báo startup.failed (uvicorn dừng)."""

from __future__ import annotations

from typing import Any

import mcp_docs.main as main
from mcp_docs.ports import IndexConfigError, RetrievalUnavailable


class _Rt:
    def __init__(self, exc: Exception | None) -> None:
        self.exc = exc
        self.app = self._app

    async def _app(self, scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "lifespan.startup.complete"})

    async def startup_check(self) -> None:
        if self.exc:
            raise self.exc


async def _run(monkeypatch, exc: Exception | None) -> list[dict]:
    monkeypatch.setattr(main, "build_runtime", lambda: _Rt(exc))
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "lifespan.startup"}

    async def send(msg: dict) -> None:
        sent.append(msg)

    await main._LazyApp()({"type": "lifespan"}, receive, send)
    return sent


async def test_dim_mismatch_fails_startup(monkeypatch) -> None:
    sent = await _run(monkeypatch, IndexConfigError("vector(768) != 1024"))
    assert sent == [{"type": "lifespan.startup.failed", "message": "vector(768) != 1024"}]


async def test_store_down_does_not_block_startup(monkeypatch) -> None:
    sent = await _run(monkeypatch, RetrievalUnavailable("database"))
    assert sent == [{"type": "lifespan.startup.complete"}]


async def test_ok_startup_delegates(monkeypatch) -> None:
    assert (await _run(monkeypatch, None))[0]["type"] == "lifespan.startup.complete"
