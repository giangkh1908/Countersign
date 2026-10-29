"""Điểm vào ASGI của mcp_tickets: `uvicorn mcp_tickets.main:app`."""

from fastapi import FastAPI

app = FastAPI(title="tickets-mcp")

# TODO: endpoint `/mcp` (Streamable HTTP) sẽ mount từ ToolServerHost.asgi_app() sau spike M0.
# permissive adapters (IntentIssuer/ApprovalVerifier) chỉ khi ACME_ENV=eval.


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
