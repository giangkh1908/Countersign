"""Điểm vào ASGI của mcp_analytics: `uvicorn mcp_analytics.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="analytics-mcp")

# TODO: endpoint `/mcp` (Streamable HTTP) sẽ mount từ ToolServerHost.asgi_app() sau spike M0.


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
