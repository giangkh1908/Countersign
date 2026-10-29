from approval_signer.main import app
from approval_signer.settings import Settings
from fastapi.testclient import TestClient


def test_healthz() -> None:
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_settings() -> None:
    assert Settings().acme_env in {"dev", "test", "bench", "eval"}
