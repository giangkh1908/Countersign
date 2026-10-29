from fastapi.testclient import TestClient
from policy_sidecar.main import app
from policy_sidecar.settings import Settings


def test_healthz() -> None:
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_settings() -> None:
    assert Settings().acme_env in {"dev", "test", "bench", "eval"}
