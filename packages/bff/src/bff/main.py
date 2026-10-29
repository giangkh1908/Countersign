"""Điểm vào ASGI của bff: `uvicorn bff.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="bff")

# TODO: mount SPA (StaticFiles + fallback index.html) từ BFF_STATIC_DIR.


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
