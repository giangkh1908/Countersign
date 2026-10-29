"""Entrypoint FastAPI của mock_provider: `uvicorn mock_provider.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="Mock Provider")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Không auth; chỉ báo sống (contracts §1)."""
    return {"status": "ok"}


# TODO: GET /metrics, bắt buộc `Authorization: Bearer ${METRICS_TOKEN}` (contracts §1).
# TODO: /__control (chaos: latency, lỗi 429/5xx, ngắt stream) - contracts §1.
