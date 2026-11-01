"""Adapter `http` của ServiceProbe: GET `<origin>/healthz` của MCP server."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx

from ..ports.service_probe import ServiceProbe


class HttpServiceProbe(ServiceProbe):
    def __init__(self, *, attempts: int = 3, delay_s: float = 1.0, timeout_s: float = 2.0) -> None:
        self._attempts = max(1, attempts)
        self._delay_s = delay_s
        self._timeout_s = timeout_s

    async def is_reachable(self, url: str) -> bool:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return False
        health = f"{parts.scheme}://{parts.netloc}/healthz"
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            for i in range(self._attempts):
                try:
                    if (await client.get(health)).status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
                if i < self._attempts - 1:
                    await asyncio.sleep(self._delay_s)
        return False
