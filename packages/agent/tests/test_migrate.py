from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from agent.migrate import migrate, owner_dsn
from agent.settings import Settings


class FakeSaver:
    def __init__(self) -> None:
        self.setups = 0

    async def setup(self) -> None:
        self.setups += 1


def test_owner_dsn_builds_from_password_and_quotes():
    s = Settings(agent_owner_password="p@ss/w d", pg_host="db", pg_port=6543)
    assert owner_dsn(s) == "postgresql://ag_owner:p%40ss%2Fw%20d@db:6543/agent"


def test_owner_dsn_prefers_explicit_url():
    s = Settings(agent_database_owner_url="postgresql://x@y/agent", agent_owner_password="ignored")
    assert owner_dsn(s) == "postgresql://x@y/agent"


def test_owner_dsn_requires_credentials():
    with pytest.raises(SystemExit):
        owner_dsn(Settings())


async def test_migrate_runs_setup_with_owner_dsn():
    saver, seen = FakeSaver(), []

    @asynccontextmanager
    async def opener(dsn: str):
        seen.append(dsn)
        yield saver

    await migrate(Settings(agent_owner_password="pw"), opener)
    assert saver.setups == 1 and seen == ["postgresql://ag_owner:pw@postgres:5432/agent"]
