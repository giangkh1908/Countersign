"""Điểm vào ASGI của mcp_docs: `uvicorn mcp_docs.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="docs-mcp")

# TODO: endpoint `/mcp` (Streamable HTTP) sẽ mount từ ToolServerHost.asgi_app() sau spike M0.


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
