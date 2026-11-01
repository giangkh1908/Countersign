import httpx
import pytest
from fastapi import FastAPI
from mock_provider.main import create_app
from mock_provider.settings import Settings

METRICS_TOKEN = "metrics-secret"
CONTROL_TOKEN = "control-secret"


def make_settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "mock_ttft_ms": 0,
        "mock_tokens_per_sec": 0,
        "mock_output_tokens": 8,
        "mock_hang_s": 0.05,
        "metrics_token": METRICS_TOKEN,
        "mock_control_token": CONTROL_TOKEN,
    }
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
def http(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")
