"""Điểm vào ASGI của mcp_docs: `uvicorn mcp_docs.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="docs-mcp")

# TODO: dựng host bằng acme_common.factory.build_tool_server_host + acme_common.mcp.AuthMiddleware (ADR-003).


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
