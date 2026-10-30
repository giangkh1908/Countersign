"""Agent tuỳ chọn (R0): agent chuyên trách phụ thuộc MCP server không bắt buộc.

URL rỗng => tắt, không probe. URL có nhưng MCP không trả khoẻ lúc khởi động => tắt và log.
Agent vẫn chạy khoẻ, router chỉ còn docs / trả lời trực tiếp. Chỉ import port và Settings.
"""

from __future__ import annotations

import logging

from .ports.service_probe import ServiceProbe
from .settings import Settings

log = logging.getLogger(__name__)

# route -> tên trường Settings chứa URL MCP của nó
OPTIONAL_AGENT_URLS: dict[str, str] = {"ticket": "mcp_tickets_url"}


async def resolve_enabled_agents(settings: Settings, probe: ServiceProbe) -> Settings:
    """Trả Settings mà `enabled_agents` đã loại agent tuỳ chọn không dùng được."""
    keep: list[str] = []
    for name in settings.enabled_agents:
        field = OPTIONAL_AGENT_URLS.get(name)
        if field is None:
            keep.append(name)
            continue
        url = str(getattr(settings, field) or "").strip()
        if not url:
            log.info("optional_agent_disabled", extra={"fields": {"agent": name, "why": "no_url"}})
        elif not await probe.is_reachable(url):
            log.info(
                "optional_agent_disabled", extra={"fields": {"agent": name, "why": "unreachable"}}
            )
        else:
            keep.append(name)
    return settings.model_copy(update={"agents_enabled": ",".join(keep)})
