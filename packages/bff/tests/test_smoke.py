from bff.main import app
from fastapi.testclient import TestClient


def test_healthz() -> None:
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
