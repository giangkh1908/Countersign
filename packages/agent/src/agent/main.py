"""Điểm vào ASGI của agent: `uvicorn agent.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="agent")

# Không có APPROVAL_SIGNER_URL: agent không được gọi approval-signer (D13).


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
