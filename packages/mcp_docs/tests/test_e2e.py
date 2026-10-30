"""Toàn bộ qua ASGI: McpSdkHost + AuthMiddleware + ToolInvoker + endpoint forget (token ký thật)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import fakeredis.aioredis
import httpx
import pytest
from acme_common.adapters.oidc_jwks import OidcJwksTokenVerifier
from acme_common.http import RetryingHttpClient
from acme_common.services.taint import get_taint, thread_key
from acme_common.testing import (
    ISSUER,
    FakeClock,
    FakeEventSink,
    FakeJwksEndpoint,
    FakeRateLimiter,
    TestSigner,
    make_claims,
)
from mcp_docs.main import build_runtime
from mcp_docs.settings import Settings
from mcp_docs.testing import SAMPLE_STORE as STORE
from mcp_docs.testing import FakeRetriever

HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class E2E:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.signer = TestSigner("ES256", "k1")
        self.redis = fakeredis.aioredis.FakeRedis()
        self.sink = FakeEventSink()
        jwks = FakeJwksEndpoint([self.signer])

        def verifier(claims: tuple[str, ...]) -> OidcJwksTokenVerifier:
            return OidcJwksTokenVerifier(
                issuer=ISSUER,
                jwks_url=jwks.JWKS_URL,
                http=RetryingHttpClient(transport=jwks.transport(), max_attempts=1),
                clock=self.clock,
                allowed_azp=set(),
                required_scopes=set(),
                required_claims=claims,
            )

        s = Settings(
            mcp_database_url="postgresql://x@localhost:1/k",
            mcp_allowed_azp="agent-service",
            mcp_allowed_hosts="docs-mcp:8101",
        )
        self.rt = build_runtime(
            s,
            clock=self.clock,
            verifier=verifier(("sub", "dept", "clearance")),
            forget_verifier=verifier(("sub",)),
            retriever=FakeRetriever(STORE),
            redis=self.redis,
            audit=self.sink,
            limiter=FakeRateLimiter(),
        )

    def token(self, **kw: Any) -> str:
        kw.setdefault("aud", "docs-mcp")
        kw.setdefault("scope", "docs:read")
        kw.setdefault("azp", "agent-service")
        return self.signer.sign(make_claims(self.clock.now().timestamp(), **kw))

    @asynccontextmanager
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        inner = self.rt.host.asgi_app()
        async with (
            inner.router.lifespan_context(inner),  # type: ignore[attr-defined]
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.rt.app), base_url="http://docs-mcp:8101"
            ) as c,
        ):
            yield c


def parse(resp: httpx.Response) -> dict[str, Any]:
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        data = [ln[5:].strip() for ln in resp.text.splitlines() if ln.startswith("data:")]
        return json.loads(data[-1])
    return json.loads(resp.text)


def call(args: dict[str, Any], thread: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"name": "search_documents", "arguments": args}
    if thread:
        params["_meta"] = {"io.acme/thread_id": thread}
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


@pytest.fixture
def e2e() -> E2E:
    return E2E()


async def test_search_over_mcp_returns_structured_untrusted_results(e2e: E2E) -> None:
    tok = e2e.token(dept=["SALES"], clearance=2, sub="u-sales")
    async with e2e.client() as c:
        r = await c.post(
            "/mcp",
            headers={**HDR, "Authorization": f"Bearer {tok}"},
            json=call({"query": "lương thưởng", "top_k": 5}, "thr-1"),
        )
    body = parse(r)
    res = body["result"]
    assert not res.get("isError"), res
    out = res["structuredContent"]
    assert out["mode"] == "hybrid" and out["results"]
    assert all(x["trust"] == "untrusted" for x in out["results"])
    assert not any("HR" in x["source"] for x in out["results"])
    view = await get_taint(e2e.redis, "u-sales", "thr-1")
    assert view is not None and view.thread.max_class == 2


async def test_missing_scope_and_wrong_audience_rejected(e2e: E2E) -> None:
    async with e2e.client() as c:
        no_scope = e2e.token(scope="other:read")
        r1 = await c.post(
            "/mcp",
            headers={**HDR, "Authorization": f"Bearer {no_scope}"},
            json=call({"query": "ab"}),
        )
        wrong_aud = e2e.token(aud="tickets-mcp")
        r2 = await c.post(
            "/mcp",
            headers={**HDR, "Authorization": f"Bearer {wrong_aud}"},
            json=call({"query": "ab"}),
        )
    assert r1.status_code == 403 and r2.status_code == 403


async def _forget(e2e: E2E, tok: str | None, body: dict[str, Any]) -> httpx.Response:
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    transport = httpx.ASGITransport(app=e2e.rt.app)  # endpoint forget không cần lifespan của host
    async with httpx.AsyncClient(transport=transport, base_url="http://docs-mcp:8101") as c:
        return await c.post("/internal/taint/forget", headers=headers, json=body)


async def test_forget_uses_sub_from_token_not_body(e2e: E2E) -> None:
    from acme_common.services.taint import raise_taint

    await raise_taint(e2e.redis, "alice", "t1", 2, {"HR"})
    await raise_taint(e2e.redis, "bob", "t1", 2, {"HR"})
    tok = e2e.token(sub="alice", dept=["HR"])
    r = await _forget(e2e, tok, {"thread_id": "t1", "sub": "bob"})
    assert r.status_code == 204
    assert await e2e.redis.exists(thread_key("alice", "t1")) == 0
    assert await e2e.redis.exists(thread_key("bob", "t1")) == 1  # sub trong body bị bỏ qua
    assert await e2e.redis.exists("mcp:taint:alice:recent") == 1  # không đụng :recent
    assert e2e.sink.events[-1]["action"] == "taint.forget"


async def test_forget_missing_key_still_204_and_validation(e2e: E2E) -> None:
    tok = e2e.token(sub="alice")
    assert (await _forget(e2e, tok, {"thread_id": "nope"})).status_code == 204
    assert (await _forget(e2e, tok, {"thread_id": "recent"})).status_code == 400
    assert (await _forget(e2e, tok, {})).status_code == 400
    assert (await _forget(e2e, None, {"thread_id": "t"})).status_code == 401
    assert (await _forget(e2e, e2e.token(aud="tickets-mcp"), {"thread_id": "t"})).status_code == 403
    assert (await _forget(e2e, e2e.token(scope="x"), {"thread_id": "t"})).status_code == 403


async def test_forget_maintenance_client_takes_sub_from_body(e2e: E2E) -> None:
    from acme_common.services.taint import raise_taint

    await raise_taint(e2e.redis, "carol", "t9", 1, {"ALL"})
    tok = e2e.token(sub="svc-maint", azp="agent-maintenance", scope="docs:forget")
    assert (await _forget(e2e, tok, {"thread_id": "t9"})).status_code == 403  # thiếu sub
    r = await _forget(e2e, tok, {"thread_id": "t9", "sub": "carol"})
    assert r.status_code == 204 and await e2e.redis.exists(thread_key("carol", "t9")) == 0
    # azp maintenance mà thiếu scope docs:forget
    bad = e2e.token(azp="agent-maintenance", scope="docs:read")
    assert (await _forget(e2e, bad, {"thread_id": "t9", "sub": "carol"})).status_code == 403
