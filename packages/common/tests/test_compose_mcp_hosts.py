"""Mỗi MCP server trong compose phải cho phép Host nội bộ `<service>:<port>` (SDK mặc định chỉ loopback => 421)."""

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
PORTS = {"docs-mcp": "8101", "tickets-mcp": "8102", "notify-mcp": "8103"}


@pytest.mark.parametrize("service", sorted(PORTS))
def test_mcp_service_allows_internal_host_header(service: str) -> None:
    env = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"][service]["environment"]
    hosts = {h.strip() for h in str(env["MCP_ALLOWED_HOSTS"]).split(",")}
    assert f"{service}:{PORTS[service]}" in hosts
    assert env["MCP_AUDIENCE"] == service
