"""Tickets tuỳ chọn (R0): bật/tắt agent ticket theo cấu hình và theo khả năng kết nối."""

from __future__ import annotations

import pytest
from agent.availability import resolve_enabled_agents
from agent.factory import build_agent_registry, build_service_probe
from agent.ports.errors import ServiceProbeNotConfigured
from agent.settings import Settings
from agent.testing import FakeServiceProbe

TICKETS = "http://tickets-mcp:8102/mcp"


def _s(**kw: str) -> Settings:
    return Settings(acme_env="test", **{"agents_enabled": "docs,ticket", **kw})


async def test_tickets_on_when_reachable():
    probe = FakeServiceProbe({TICKETS})
    s = await resolve_enabled_agents(_s(mcp_tickets_url=TICKETS), probe)
    assert build_agent_registry(s).routes() == ["docs", "ticket"]
    assert "tickets-mcp" in s.mcp_servers
    assert probe.calls == [TICKETS]


async def test_tickets_off_when_url_empty_without_probing():
    probe = FakeServiceProbe({TICKETS})
    s = await resolve_enabled_agents(_s(mcp_tickets_url=""), probe)
    assert build_agent_registry(s).routes() == ["docs"]
    assert "tickets-mcp" not in s.mcp_servers
    assert probe.calls == []


async def test_tickets_off_when_unreachable():
    s = await resolve_enabled_agents(_s(mcp_tickets_url=TICKETS), FakeServiceProbe())
    reg = build_agent_registry(s)
    assert reg.routes() == ["docs"]
    assert set(reg.access_map()) == {"docs_agent"}


async def test_non_optional_agents_untouched():
    probe = FakeServiceProbe()
    s = await resolve_enabled_agents(_s(agents_enabled="docs"), probe)
    assert s.enabled_agents == ("docs",) and probe.calls == []


def test_probe_unknown_name():
    with pytest.raises(ServiceProbeNotConfigured):
        build_service_probe("nope", _s())
    assert build_service_probe("http", _s()) is not None


async def test_refresh_enables_tickets_when_mcp_comes_up_later():
    from agent.container import refresh_optional_agents
    from agent.testing import FakeToolProvider, build_test_container

    c = build_test_container(FakeToolProvider(), {})
    c.base_settings = c.settings.model_copy(update={"mcp_tickets_url": TICKETS})
    c.write_broker = c.broker
    c.settings = c.base_settings.model_copy(update={"agents_enabled": "docs"})
    probe = FakeServiceProbe()
    assert await refresh_optional_agents(c, probe) is False
    assert c.settings.enabled_agents == ("docs",)
    probe.up.add(TICKETS)
    assert await refresh_optional_agents(c, probe) is True
    assert c.registry.routes() == ["docs", "ticket"]
    assert await refresh_optional_agents(c, probe) is False
