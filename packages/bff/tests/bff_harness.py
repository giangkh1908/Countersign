"""Harness test offline cho bff: IdP/agent/signer giả qua httpx.MockTransport, Redis giả (fakeredis),
`FakeTokenVerifier`/`FakeTokenBroker`, trình duyệt giả có quét token trong mọi response."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import fakeredis
import httpx
import pytest
from acme_common.ports import Principal
from acme_common.testing import ISSUER, FakeClock, FakeTokenBroker, FakeTokenVerifier

from bff.main import create_app
from bff.settings import Settings

PUBLIC = "https://bff.test"
THREAD = "0b7a3a5e-7b0d-4a42-9c35-7c0e6f1d2a11"
MSG_ID = "5f6f6c0a-2a39-4a41-8a43-1f6f6d7e8a90"
APPROVAL_TOKEN = "APPROVAL-TOKEN-do-not-leak"
INTENT_JWS = "eyJJTlRFTlQ.SECRET-JWS.PART"
SHA = "a" * 64


def b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sse(*frames: tuple[str, dict[str, Any] | str]) -> bytes:
    out = []
    for i, (event, data) in enumerate(frames, 1):
        payload = data if isinstance(data, str) else json.dumps(data)
        out.append(f"id: {i}\nevent: {event}\ndata: {payload}\n\n")
    return "".join(out).encode()


def interrupt_frame(interrupt_id: str = "int_1", intent_id: str = "intent-1") -> tuple[str, Any]:
    return (
        "interrupt",
        {
            "interrupt_id": interrupt_id,
            "payload": {
                "kind": "write_approval",
                "intent_id": intent_id,
                "intent_jws": INTENT_JWS,
                "op": "close_ticket",
                "expires_at": "2026-01-01T00:05:00Z",
            },
        },
    )


@dataclass
class FakeIdp:
    verifier: FakeTokenVerifier
    nonce: str = "n"
    issued: list[str] = field(default_factory=list)
    refresh_calls: int = 0
    revoked: list[str] = field(default_factory=list)
    fail_refresh: bool = False
    n: int = 0

    def principal(self) -> Principal:
        return Principal(
            sub="user-1",
            audience=("chat-ui",),
            azp="chat-ui",
            scopes=frozenset(),
            expires_at=9e12,
            roles=("employee",),
            dept=("CS",),
            clearance=1,
        )

    def _tokens(self, with_id: bool) -> dict[str, Any]:
        self.n += 1
        access, refresh = f"ACCESS-secret-{self.n}", f"REFRESH-secret-{self.n}"
        body: dict[str, Any] = {"access_token": access, "refresh_token": refresh, "expires_in": 300}
        self.verifier.add(access, self.principal())
        self.issued += [access, refresh]
        if with_id:
            idt = f"h.{b64({'sub': 'user-1', 'nonce': self.nonce, 'name': 'Nguyễn A', 'email': 'a@acme.vn'})}.sig{self.n}"
            self.verifier.add(idt, self.principal())
            self.issued.append(idt)
            body["id_token"] = idt
        return body

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/.well-known/openid-configuration"):
            base = f"{req.url.scheme}://{req.url.host}/realms/acme/protocol/openid-connect"
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": f"{base}/auth",
                    "token_endpoint": f"{base}/token",
                    "revocation_endpoint": f"{base}/revoke",
                    "end_session_endpoint": f"{base}/logout",
                },
            )
        form = parse_qs(req.content.decode())
        assert req.headers["authorization"].startswith("Basic ")  # client_secret_basic
        if path.endswith("/token"):
            grant = form["grant_type"][0]
            if grant == "authorization_code":
                assert form["code_verifier"][0]
                return httpx.Response(200, json=self._tokens(with_id=True))
            if grant == "refresh_token":
                self.refresh_calls += 1
                if self.fail_refresh:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self._tokens(with_id=False))
        if path.endswith("/revoke"):
            self.revoked.append(form["token"][0])
            return httpx.Response(200)
        return httpx.Response(404)


@dataclass
class FakeBackends:
    """Agent + signer giả. Kiểm token đúng audience (token giả có dạng `fake:<aud>:<n>`)."""

    agent_body: bytes = b""
    agent_stream: Callable[[], AsyncIterator[bytes]] | None = None
    agent_status: int = 200
    calls: list[tuple[str, str, str, dict[str, Any] | None]] = field(default_factory=list)
    signer_error: tuple[int, str] | None = None
    sha: str = SHA

    def __post_init__(self) -> None:
        self.agent_body = sse(
            ("run_start", {"run_id": "r1", "thread_id": THREAD, "request_ids": []}),
            ("token", {"text": "Xin chào", "node": "direct_answer"}),
            ("done", {"status": "completed", "message_id": "m1"}),
        )

    def __call__(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        auth = req.headers.get("authorization", "")
        body = json.loads(req.content) if req.content else None
        self.calls.append((host, req.method, path, body))
        if host == "agent.test":
            if not auth.startswith("Bearer fake:agent-service:"):
                return httpx.Response(401, json={"error": {"code": "unauthorized"}})
            return self._agent(req, path, body)
        if host == "signer.test":
            if not auth.startswith("Bearer fake:approval-signer:"):
                return httpx.Response(401, json={"error": {"code": "unauthorized"}})
            if self.signer_error:
                status, code = self.signer_error
                return httpx.Response(status, json={"error": {"code": code}})
            if path == "/v1/intents/verify":
                return httpx.Response(200, json=self._render())
            if path == "/v1/approvals":
                return httpx.Response(
                    200,
                    json={
                        "approval_token": APPROVAL_TOKEN,
                        "jti": "j1",
                        "expires_at": "2026-01-01T00:02:00Z",
                    },
                )
        return httpx.Response(404)

    def _render(self) -> dict[str, Any]:
        return {
            "intent_id": "intent-1",
            "op": "close_ticket",
            "target": {"ticket_code": "TCK-1"},
            "risk_flags": ["destructive"],
            "expires_at": "2026-01-01T00:05:00Z",
            "intent_sha256": self.sha,
            "server_time": "2026-01-01T00:00:00Z",
            "display": {
                "title": "Đóng ticket TCK-1",
                "risk": "medium",
                "display_fields": [
                    {
                        "path": "target.ticket_code",
                        "label": "Ticket",
                        "kind": "ticket_ref",
                        "before": "TCK-1",
                        "after": "TCK-1",
                        "changed": False,
                        "sensitive": False,
                    },
                ],
            },
        }

    def _agent(self, req: httpx.Request, path: str, body: Any) -> httpx.Response:
        sse_headers = {"content-type": "text/event-stream"}
        if path == "/v1/threads" and req.method == "POST":
            return httpx.Response(
                201, json={"thread_id": THREAD, "created_at": "2026-01-01T00:00:00Z"}
            )
        if path == "/v1/threads" and req.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"thread_id": THREAD, "title": "t", "last_active_at": "x", "total_cost_usd": 0}
                ],
            )
        if path.endswith("/runs") or path.endswith("/resume"):
            if self.agent_status != 200:
                return httpx.Response(self.agent_status, json={"error": {"code": "conflict"}})
            if self.agent_stream is not None:
                return httpx.Response(200, headers=sse_headers, stream=_Stream(self.agent_stream))
            return httpx.Response(200, headers=sse_headers, content=self.agent_body)
        if path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "messages": [{"role": "user", "content": "hi"}],
                    "pending_interrupt": interrupt_frame()[1],
                    "cost": {"thread_usd": 0.1},
                },
            )
        if path.startswith("/v1/requests/"):
            return httpx.Response(
                200,
                json={
                    "request_id": "r1",
                    "cost_usd": 0.01,
                    "alias": "acme-fast",
                    "tokens_in": 1,
                    "tokens_out": 2,
                    "cache": "miss",
                    "extra": "x",
                },
            )
        if path == "/v1/internal/evict":
            return httpx.Response(204)
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    def paths(self, host: str) -> list[str]:
        return [p for h, _, p, _ in self.calls if h == host]


class _Stream(httpx.AsyncByteStream):
    def __init__(self, factory: Callable[[], AsyncIterator[bytes]]) -> None:
        self._factory = factory

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._factory():
            yield chunk


class Browser:
    """Trình duyệt giả: giữ cookie, tự gắn Origin + X-CSRF-Token (đọc cookie csrf như JS)."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.seen: list[httpx.Response] = []
        self.csrf_cookie = "__Host-csrf"
        self.sid_cookie = "__Host-sid"

    async def request(
        self,
        method: str,
        url: str,
        *,
        csrf: bool = True,
        origin: str | None = PUBLIC,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> httpx.Response:
        h = dict(headers or {})
        if origin is not None:
            h.setdefault("Origin", origin)
        if (
            csrf
            and method not in {"GET", "HEAD"}
            and (tok := self.client.cookies.get(self.csrf_cookie))
        ):
            h.setdefault("X-CSRF-Token", tok)
        resp = await self.client.request(method, url, headers=h, **kw)
        self.seen.append(resp)
        return resp

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw: Any) -> httpx.Response:
        return await self.request("POST", url, **kw)

    async def delete(self, url: str, **kw: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kw)

    async def login(self, idp: FakeIdp, nonce: str = "nonce-ok") -> httpx.Response:
        start = await self.get("/auth/login?return_to=/chat")
        assert start.status_code == 302, start.text
        q = parse_qs(urlsplit(start.headers["location"]).query)
        idp.nonce = nonce if nonce != "nonce-ok" else q["nonce"][0]
        done = await self.get(f"/auth/callback?code=c1&state={q['state'][0]}")
        assert done.status_code == 302, done.text
        return done


@dataclass
class Env:
    settings: Settings
    app: Any
    redis: Any
    clock: FakeClock
    idp: FakeIdp
    backends: FakeBackends
    broker: FakeTokenBroker
    verifier: FakeTokenVerifier
    browser: Browser

    @property
    def container(self) -> Any:
        return self.app.state.container


def make_settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "acme_env": "test",
        "bff_public_url": PUBLIC,
        "bff_session_key": base64.urlsafe_b64encode(bytes(range(32))).decode(),
        "bff_oidc_client_secret": "client-secret",
        "bff_agent_url": "http://agent.test",
        "bff_signer_url": "http://signer.test",
        "keycloak_issuer": ISSUER,
        "bff_stream_heartbeat_s": 0.05,
    }
    base.update(over)
    return Settings(**base)


async def build_env(settings: Settings | None = None, *, deny: tuple[str, ...] = ()) -> Env:
    settings = settings or make_settings()
    clock = FakeClock()
    verifier = FakeTokenVerifier()
    idp = FakeIdp(verifier)
    backends = FakeBackends()

    def dispatch(req: httpx.Request) -> httpx.Response:
        return (idp if req.url.host == "idp.test" else backends)(req)

    broker = FakeTokenBroker(clock, deny=deny)
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    app = create_app(
        settings,
        redis=redis,
        clock=clock,
        verifier=verifier,
        broker=broker,
        transport=httpx.MockTransport(dispatch),
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC)
    browser = Browser(client, settings)
    return Env(settings, app, redis, clock, idp, backends, broker, verifier, browser)


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch) -> None:
    """`CommonSettings` đọc `.env` theo đường dẫn tương đối; chạy trong thư mục trống."""
    monkeypatch.chdir(tmp_path)


def _scan_for_secrets(env: Env) -> None:
    secrets = [*env.idp.issued, APPROVAL_TOKEN, INTENT_JWS]
    for resp in env.browser.seen:
        blob = resp.text + "\n" + "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
        for s in secrets:
            assert s not in blob, f"secret leaked in {resp.request.method} {resp.request.url.path}"
        assert not re.search(r"fake:(agent-service|approval-signer)", blob), (
            "exchanged token leaked"
        )
        assert "Bearer " not in blob


@pytest.fixture
async def env():
    e = await build_env()
    yield e
    _scan_for_secrets(e)  # quét token trong MỌI response của test
    await e.browser.client.aclose()
    await e.container.aclose()


@pytest.fixture
async def logged_in(env: Env) -> Env:
    await env.browser.login(env.idp)
    return env
