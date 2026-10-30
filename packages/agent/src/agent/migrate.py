"""Job migration của agent: tạo bảng checkpointer LangGraph (`setup()` là DDL) bằng role `ag_owner`.

Runtime dùng role `ag_app` (chỉ DML) nên không tự `setup()` được (factory.py). Chạy: `python -m agent.migrate`.
Idempotent; bảng do `ag_owner` tạo tự cấp DML cho `ag_app` nhờ DEFAULT PRIVILEGES (infra/postgres 30-agent.sql).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from urllib.parse import quote

from .settings import Settings

log = logging.getLogger("agent.migrate")
SaverOpener = Callable[[str], AbstractAsyncContextManager[Any]]


def owner_dsn(s: Settings) -> str:
    if s.agent_database_owner_url:
        return s.agent_database_owner_url
    if not s.agent_owner_password:
        raise SystemExit("AGENT_DATABASE_OWNER_URL hoặc AGENT_OWNER_PASSWORD(_FILE) là bắt buộc")
    return f"postgresql://ag_owner:{quote(s.agent_owner_password, safe='')}@{s.pg_host}:{s.pg_port}/agent"


@asynccontextmanager
async def _open_postgres_saver(dsn: str) -> AsyncIterator[Any]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        yield saver


async def migrate(settings: Settings, open_saver: SaverOpener = _open_postgres_saver) -> None:
    async with open_saver(owner_dsn(settings)) as saver:
        await saver.setup()
    log.info("agent checkpointer schema ready")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate(Settings()))


if __name__ == "__main__":
    main()
