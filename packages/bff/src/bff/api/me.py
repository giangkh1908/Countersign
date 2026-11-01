"""Router thông tin người dùng. Mỏng, gọi services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from ..factory import Container
from ..services.session import SessionData
from .deps import get_container, read_session

router = APIRouter()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/api/me")
async def me(
    s: SessionData = Depends(read_session), c: Container = Depends(get_container)
) -> dict[str, Any]:
    now = c.clock.now().timestamp()
    absolute = s.created_at + c.settings.bff_session_abs_s
    user = s.user
    return {
        "sub": s.sub,
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "roles": user.get("roles", []),
        "depts": user.get("depts", []),
        "clearance": user.get("clearance", 0),
        "csrf_token": s.csrf,
        "idle_expires_at": _iso(min(now + c.settings.bff_session_idle_s, absolute)),
        "absolute_expires_at": _iso(absolute),
        "server_time": _iso(now),
        "link_allowlist": list(c.settings.link_allowlist),
    }
