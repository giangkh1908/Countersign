from fastapi.testclient import TestClient
from mcp_tickets.main import app


def test_healthz() -> None:
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
