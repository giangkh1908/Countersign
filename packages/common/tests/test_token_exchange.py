from urllib.parse import parse_qs

import httpx
import pytest
from acme_common.adapters.oauth_token_exchange import OAuthTokenExchangeBroker
from acme_common.caching_token_broker import CachingTokenBroker
from acme_common.http import RetryingHttpClient
from acme_common.ports import Principal, TokenExchangeDenied, TokenServiceUnavailable
from acme_common.testing import FakeClock, FakeTokenBroker, TestSigner, make_claims

SECRET = "s3cr3t-value"
signer = TestSigner("ES256", "k1")
USER_TOKEN = "user.jwt.value"


def principal(clock: FakeClock, **kw) -> Principal:
    base = dict(
        sub="user-1",
        audience=("agent-service",),
        azp="chat-ui",
        scopes=frozenset({"agent:invoke"}),
        expires_at=clock.now().timestamp() + 300,
        sid="s1",
    )
    base.update(kw)
    return Principal(**base)


def broker(handler, **kw) -> OAuthTokenExchangeBroker:
    http = RetryingHttpClient(transport=httpx.MockTransport(handler), max_attempts=1)
    return OAuthTokenExchangeBroker(
        token_url="https://idp.test/token", client_id="agent-service", client_secret=SECRET,
        http=http, ignored_scopes=("openid", "acme-claims"), **kw,
    )  # fmt: skip


def issuing(clock: FakeClock, **claim_overrides):
    """Mock IdP: trả token với claim cho trước (mặc định đúng aud/scope đã xin)."""
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        seen.append(form)
        claims = make_claims(
            clock.now().timestamp(),
            aud=form["audience"][0],
            azp="agent-service",
            scope=form["scope"][0] + " acme-claims",
        )
        claims.update(claim_overrides)
        return httpx.Response(200, json={"access_token": signer.sign(claims)})

    return handler, seen


async def test_exchange_sends_one_audience_and_returns_token() -> None:
    clock = FakeClock()
    handler, seen = issuing(clock)
    tok = await broker(handler).token_for(
        principal(clock), USER_TOKEN, "tickets-mcp", ["tickets:read"]
    )
    form = seen[0]
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:token-exchange"]
    assert form["audience"] == ["tickets-mcp"] and form["scope"] == ["tickets:read"]
    assert form["subject_token"] == [USER_TOKEN]
    assert (tok.audience, tok.scopes, tok.sub) == ("tickets-mcp", {"tickets:read"}, "user-1")
    assert SECRET not in repr(tok) and tok.value not in repr(tok)


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"aud": ["tickets-mcp", "llm-gateway"]}, "audience_mismatch"),
        ({"aud": "llm-gateway"}, "audience_mismatch"),
        ({"scope": "tickets:read llm:invoke"}, "scope_escalation"),
        ({"sub": "someone-else"}, "subject_mismatch"),
    ],
)
async def test_postconditions_violation_raises(override: dict, reason: str) -> None:
    clock = FakeClock()
    handler, _ = issuing(clock, **override)
    with pytest.raises(TokenExchangeDenied) as e:
        await broker(handler).token_for(
            principal(clock), USER_TOKEN, "tickets-mcp", ["tickets:read"]
        )
    assert e.value.reason == reason


@pytest.mark.parametrize("status", [400, 403])
async def test_idp_denial_is_translated_without_leaking_detail(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"error": "invalid_scope", "error_description": f"bad {USER_TOKEN}"}
        )

    clock = FakeClock()
    with pytest.raises(TokenExchangeDenied) as e:
        await broker(handler).token_for(principal(clock), USER_TOKEN, "approval-signer", ["x"])
    assert e.value.reason == "invalid_scope" and e.value.http_status == status
    assert USER_TOKEN not in str(e.value) and SECRET not in str(e.value)


async def test_idp_down_is_unavailable_not_denied() -> None:
    clock = FakeClock()
    with pytest.raises(TokenServiceUnavailable):
        await broker(lambda r: httpx.Response(503)).token_for(
            principal(clock), USER_TOKEN, "tickets-mcp", ["tickets:read"]
        )


@pytest.mark.parametrize("audience", ["", "a b", "a,b"])
async def test_multiple_audiences_rejected(audience: str) -> None:
    clock = FakeClock()
    with pytest.raises(ValueError):
        await broker(lambda r: httpx.Response(500)).token_for(
            principal(clock), USER_TOKEN, audience, ["x"]
        )


# --- CachingTokenBroker ---
async def test_cache_hit_then_expiry_by_token_exp() -> None:
    clock = FakeClock()
    inner = FakeTokenBroker(clock, ttl_s=300)
    b = CachingTokenBroker(inner, clock, skew_s=30)
    p = principal(clock, expires_at=clock.now().timestamp() + 3600)
    t1 = await b.token_for(p, USER_TOKEN, "tickets-mcp", ["b", "a"])
    t2 = await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a", "b"])  # thứ tự scope không đổi khoá
    assert t1 is t2 and len(inner.calls) == 1
    clock.advance(269)  # 300 - 30 = 270 giây hiệu lực
    await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a", "b"])
    assert len(inner.calls) == 1
    clock.advance(2)
    await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a", "b"])
    assert len(inner.calls) == 2


async def test_cache_ttl_capped_by_subject_exp() -> None:
    clock = FakeClock()
    inner = FakeTokenBroker(clock, ttl_s=300)
    b = CachingTokenBroker(inner, clock, skew_s=30)
    p = principal(clock, expires_at=clock.now().timestamp() + 100)  # subject sắp hết hạn
    await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a"])
    clock.advance(71)  # 100 - 30 = 70
    await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a"])
    assert len(inner.calls) == 2


async def test_cache_key_separates_session_audience_scope_and_user() -> None:
    clock = FakeClock()
    inner = FakeTokenBroker(clock)
    b = CachingTokenBroker(inner, clock)
    p = principal(clock)
    await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a"])
    await b.token_for(principal(clock, sid="s2"), USER_TOKEN, "tickets-mcp", ["a"])
    await b.token_for(principal(clock, sub="user-2"), USER_TOKEN, "tickets-mcp", ["a"])
    await b.token_for(p, USER_TOKEN, "docs-mcp", ["a"])
    await b.token_for(p, USER_TOKEN, "tickets-mcp", ["a", "b"])
    assert len(inner.calls) == 5


async def test_cache_does_not_store_errors() -> None:
    clock = FakeClock()
    inner = FakeTokenBroker(clock, deny={"approval-signer"})
    b = CachingTokenBroker(inner, clock)
    for _ in range(2):
        with pytest.raises(TokenExchangeDenied):
            await b.token_for(principal(clock), USER_TOKEN, "approval-signer", ["x"])
    assert len(inner.calls) == 2
