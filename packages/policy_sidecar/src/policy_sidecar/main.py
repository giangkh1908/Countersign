"""Entrypoint FastAPI của policy_sidecar: `uvicorn policy_sidecar.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="Policy Sidecar")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Không auth; chỉ báo sống (contracts §1)."""
    return {"status": "ok"}


# TODO: GET /metrics, bắt buộc `Authorization: Bearer ${METRICS_TOKEN}` (contracts §1).
