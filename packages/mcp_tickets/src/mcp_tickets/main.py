"""Điểm vào ASGI của mcp_tickets: `uvicorn mcp_tickets.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="tickets-mcp")

# TODO: dựng host bằng acme_common.factory.build_tool_server_host + acme_common.mcp.AuthMiddleware (ADR-003).
# permissive adapters (IntentIssuer/ApprovalVerifier) chỉ khi ACME_ENV=eval.


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
