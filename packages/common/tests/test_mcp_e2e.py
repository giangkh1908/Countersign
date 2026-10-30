"""AuthMiddleware + McpSdkHost + ToolInvoker chạy offline qua ASGI (không socket)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from acme_common.adapters.mcp_sdk import McpSdkHost
from acme_common.adapters.oidc_jwks import OidcJwksTokenVerifier
from acme_common.http import RetryingHttpClient
from acme_common.mcp import AuthMiddleware, CallerContext, ToolInvoker
from acme_common.ports import ToolSpec
from acme_common.testing import (
    ISSUER,
    FakeClock,
    FakeEventSink,
    FakeJwksEndpoint,
    FakeRateLimiter,
    TestSigner,
    make_claims,
)

AUD = "docs-mcp"
SCHEMA = {
    "type": "object",
    "properties": {"q": {"type": "string", "maxLength": 50}},
    "required": ["q"],
    "additionalProperties": False,
}
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class Env:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.signer = TestSigner("ES256", "k1")
        self.sink = FakeEventSink()
        self.host = McpSdkHost("docs-mcp", allowed_hosts=["docs-mcp:8101"])
        jwks = FakeJwksEndpoint([self.signer])
        verifier = OidcJwksTokenVerifier(
            issuer=ISSUER,
            jwks_url=jwks.JWKS_URL,
            http=RetryingHttpClient(transport=jwks.transport(), max_attempts=1),
            clock=self.clock,
            allowed_azp=set(),
            required_scopes=set(),
            required_claims=("sub", "dept", "clearance"),
        )
        self.invoker = ToolInvoker(
            server="docs-mcp",
            limiter=FakeRateLimiter(),
            audit=self.sink,
            clock=self.clock,
            audit_sync=False,
        )
        self.seen: list[CallerContext] = []
        spec = ToolSpec(
            name="whoami",
            description="who",
            input_schema=SCHEMA,
            required_scopes=("docs:read",),
        )

        async def whoami(ctx: CallerContext, args: dict[str, Any]) -> dict[str, Any]:
            self.seen.append(ctx)
            return {"sub": ctx.principal.sub, "dept": list(ctx.principal.dept), "q": args["q"]}

        self.host.register(spec, self.invoker.wrap(spec, whoami))
        self.app = AuthMiddleware(
            self.host.asgi_app(),
            verifier=verifier,
            audience=AUD,
            resource_url="http://docs-mcp:8101",
            required_scopes_for=lambda n: ("docs:read",) if n == "whoami" else None,
        )

    def token(self, **kw: Any) -> str:
        kw.setdefault("aud", AUD)
        kw.setdefault("scope", "docs:read")
        return self.signer.sign(make_claims(self.clock.now().timestamp(), **kw))

    @asynccontextmanager
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        inner = self.host.asgi_app()
        async with (
            inner.router.lifespan_context(inner),  # type: ignore[attr-defined]
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url="http://docs-mcp:8101"
            ) as c,
        ):
            yield c


def rpc(name: str, args: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name, "arguments": args}
    if meta:
        params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


def parse(resp: httpx.Response) -> dict[str, Any]:
    text = resp.text
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        return json.loads(data[-1])
    return json.loads(text)


@pytest.fixture
def env() -> Env:
    return Env()


async def test_valid_token_tool_sees_sub_and_dept(env: Env) -> None:
    async with env.client() as c:
        r = await c.post(
            "/mcp",
            json=rpc("whoami", {"q": "x"}, {"io.acme/thread_id": "T1"}),
            headers={**HDR, "Authorization": f"Bearer {env.token(sub='u-42')}"},
        )
    assert r.status_code == 200, r.text
    result = parse(r)["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"sub": "u-42", "dept": ["CS"], "q": "x"}
    ctx = env.seen[0]
    assert ctx.principal.sub == "u-42" and ctx.thread_id == "T1"
    ev = env.sink.events[0]
    assert ev["decision"] == "allow" and ev["end_user_sub"] == "u-42" and ev["resource"] == "whoami"


async def test_wrong_audience_rejected_with_challenge(env: Env) -> None:
    async with env.client() as c:
        r = await c.post(
            "/mcp",
            json=rpc("whoami", {"q": "x"}),
            headers={**HDR, "Authorization": f"Bearer {env.token(aud='tickets-mcp')}"},
        )
    assert r.status_code in (401, 403)
    assert (
        "Bearer" in r.headers["www-authenticate"]
        and "resource_metadata" in r.headers["www-authenticate"]
    )
    assert not env.seen


async def test_missing_token_401_expired_401(env: Env) -> None:
    async with env.client() as c:
        r = await c.post("/mcp", json=rpc("whoami", {"q": "x"}), headers=HDR)
        assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
        tok = env.token(ttl_s=10)
        env.clock.advance(11)
        r = await c.post(
            "/mcp",
            json=rpc("whoami", {"q": "x"}),
            headers={**HDR, "Authorization": f"Bearer {tok}"},
        )
        assert (
            r.status_code == 401 and 'error_description="expired"' in r.headers["www-authenticate"]
        )


async def test_missing_scope_blocked_in_middleware_403(env: Env) -> None:
    async with env.client() as c:
        r = await c.post(
            "/mcp",
            json=rpc("whoami", {"q": "x"}),
            headers={**HDR, "Authorization": f"Bearer {env.token(scope='tickets:read')}"},
        )
    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r.headers["www-authenticate"]
    assert 'scope="docs:read"' in r.headers["www-authenticate"]


async def test_healthz_without_auth_and_other_paths(env: Env) -> None:
    async with env.client() as c:
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.get("/mcp")).status_code == 405
        assert (await c.get("/nope")).status_code == 404
        prm = await c.get("/.well-known/oauth-protected-resource")
        assert prm.status_code == 200 and prm.json()["resource"] == "http://docs-mcp:8101"


async def test_origin_and_batch_and_oversize_rejected(env: Env) -> None:
    h = {**HDR, "Authorization": f"Bearer {env.token()}"}
    async with env.client() as c:
        r = await c.post(
            "/mcp", json=rpc("whoami", {"q": "x"}), headers={**h, "Origin": "http://evil"}
        )
        assert r.status_code == 403
        r = await c.post("/mcp", json=[rpc("whoami", {"q": "x"})], headers=h)
        assert r.status_code == 400
        r = await c.post("/mcp", content=b"x" * 300_000, headers=h)
        assert r.status_code == 413


async def test_invalid_arguments_returned_as_tool_error_and_audited(env: Env) -> None:
    async with env.client() as c:
        r = await c.post(
            "/mcp",
            json=rpc("whoami", {"q": "x", "sub": "evil"}),
            headers={**HDR, "Authorization": f"Bearer {env.token()}"},
        )
    result = parse(r)["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["code"] == "invalid_argument"
    assert "evil" not in json.dumps(result)  # không phản chiếu giá trị người dùng
    assert env.sink.events[0]["details"]["error_code"] == "invalid_argument"
    assert not env.seen
