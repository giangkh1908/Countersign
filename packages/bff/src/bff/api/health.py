"""Router health. Mỏng, gọi services. Docs: 07 §2.6."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..adapters.oidc import OidcUnavailable
from ..factory import Container
from .deps import get_container

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(c: Container = Depends(get_container)) -> JSONResponse:
    checks: dict[str, bool] = {}
    try:
        checks["redis"] = bool(await c.redis.ping())
    except Exception:
        checks["redis"] = False
    try:
        await c.oidc.discovery(refresh=True)
        checks["idp"] = True
    except OidcUnavailable:
        checks["idp"] = False
    ok = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "unavailable", **checks}, status_code=200 if ok else 503
    )
