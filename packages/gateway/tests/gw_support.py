"""Helper dùng chung cho test gateway (import qua sys.path do conftest thêm vào)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from acme_common.ports import Principal
from acme_common.testing import FakeClock, FakeEventSink, FakeTokenVerifier
from fastapi import FastAPI
from gateway.adapters.openai_chat import OpenAIChatProvider
from gateway.container import build_container
from gateway.main import create_app
from gateway.ports.chat_provider import ChatProvider
from gateway.services.key_admin import issue_key
from gateway.settings import Settings
from gateway.testing import FakeKeyStore, provider_lookup
from mock_provider.main import create_app as create_mock_app
from mock_provider.settings import Settings as MockSettings

PEPPER = "test-pepper-" + "x" * 32
METRICS_TOKEN = "metrics-secret"
MODELS_YAML = Path(__file__).resolve().parent / "models.test.yaml"
ALL_ALIASES = ("acme-fast", "acme-smart", "acme-embed")


def make_settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "gw_key_pepper": PEPPER,
        "gw_provider_override": "mock",
        "gw_models_config": str(MODELS_YAML),
        "metrics_token": METRICS_TOKEN,
    }
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


def make_mock_app(**kw: object) -> FastAPI:
    base: dict[str, object] = {
        "mock_ttft_ms": 0,
        "mock_tokens_per_sec": 0,
        "mock_output_tokens": 8,
        "mock_hang_s": 0.05,
    }
    return create_mock_app(MockSettings(**{**base, **kw}))  # type: ignore[arg-type]


@dataclass
class Env:
    app: FastAPI
    mock_app: FastAPI
    keys: FakeKeyStore
    verifier: FakeTokenVerifier
    sink: FakeEventSink
    clock: FakeClock
    settings: Settings
    providers: Callable[[str], ChatProvider]

    async def new_key(self, **kw: object) -> str:
        """Tạo key trong FakeKeyStore, trả plaintext."""
        args: dict[str, object] = {
            "name": "test",
            "owner_type": "service",
            "owner_ref": "test",
            "dept": "IT",
            "allowed_models": ALL_ALIASES,
            "rpm": 60,
            "tpm": 100_000,
        }
        issued = issue_key(PEPPER.encode(), **{**args, **kw})  # type: ignore[arg-type]
        await self.keys.create(issued.new, "test")
        return issued.plaintext

    def gateway_client(self, api_key: str, **headers: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://gateway",
            headers={"authorization": f"Bearer {api_key}", **headers},
        )


def make_env() -> Env:
    clock, sink, keys = FakeClock(), FakeEventSink(), FakeKeyStore()
    verifier = FakeTokenVerifier()
    settings = make_settings()
    mock_app = make_mock_app()
    provider = OpenAIChatProvider(
        "http://mock",
        name="mock",
        client=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app), base_url="http://mock"
        ),
    )
    providers = provider_lookup(mock=provider)
    container = build_container(
        settings, clock=clock, keys=keys, verifier=verifier, sink=sink, providers=providers
    )
    app = create_app(settings, container)
    return Env(app, mock_app, keys, verifier, sink, clock, settings, providers)


def user_principal(
    *, aud: tuple[str, ...] = ("llm-gateway",), dept: tuple[str, ...] = ("CS",)
) -> Principal:
    return Principal(
        sub="user-42", audience=aud, azp="chat-ui", scopes=frozenset(), expires_at=2e9, dept=dept
    )
