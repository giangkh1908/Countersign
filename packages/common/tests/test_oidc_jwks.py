import jwt
import pytest
from acme_common.adapters.oidc_jwks import OidcJwksTokenVerifier
from acme_common.http import RetryingHttpClient
from acme_common.ports import TokenInvalid, TokenServiceUnavailable
from acme_common.testing import (
    ISSUER,
    FakeClock,
    FakeJwksEndpoint,
    TestSigner,
    make_claims,
)


@pytest.fixture(scope="module")
def signer() -> TestSigner:
    return TestSigner("ES256", "k1")


def make(endpoint: FakeJwksEndpoint, clock: FakeClock, **kw):
    http = RetryingHttpClient(transport=endpoint.transport(), max_attempts=1)
    kw.setdefault("allowed_azp", {"chat-ui"})
    kw.setdefault("required_scopes", {"agent:invoke"})
    return OidcJwksTokenVerifier(
        issuer=ISSUER, jwks_url=endpoint.JWKS_URL, http=http, clock=clock, **kw
    )


@pytest.mark.parametrize("alg", ["ES256", "RS256"])
async def test_valid_token_returns_principal(alg: str) -> None:
    clock, s = FakeClock(), TestSigner(alg, "kx")
    v = make(FakeJwksEndpoint([s]), clock)
    claims = make_claims(clock.now().timestamp(), sid="s1")
    p = await v.verify(s.sign(claims), "agent-service")
    assert (p.sub, p.sid, p.azp, p.dept, p.clearance) == ("user-1", "s1", "chat-ui", ("CS",), 1)
    assert p.scopes == {"agent:invoke"} and p.roles == ("employee",)


async def test_wrong_audience(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock)
    tok = signer.sign(make_claims(clock.now().timestamp(), aud="chat-ui"))
    with pytest.raises(TokenInvalid) as e:
        await v.verify(tok, "agent-service")
    assert e.value.reason == "bad_audience" and e.value.http_status == 403


async def test_expired_uses_injected_clock(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock)
    tok = signer.sign(make_claims(clock.now().timestamp(), ttl_s=60))
    assert await v.verify(tok, "agent-service")
    clock.advance(61)
    with pytest.raises(TokenInvalid) as e:
        await v.verify(tok, "agent-service")
    assert e.value.reason == "expired" and e.value.http_status == 401


async def test_wrong_issuer(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock)
    tok = signer.sign(make_claims(clock.now().timestamp(), iss="https://evil.test"))
    with pytest.raises(TokenInvalid) as e:
        await v.verify(tok, "agent-service")
    assert e.value.reason == "bad_issuer"


async def test_wrong_azp_and_missing_scope(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock)
    now = clock.now().timestamp()
    with pytest.raises(TokenInvalid) as e:
        await v.verify(signer.sign(make_claims(now, azp="agent-service")), "agent-service")
    assert e.value.reason == "bad_azp"
    with pytest.raises(TokenInvalid) as e:
        await v.verify(signer.sign(make_claims(now, scope="docs:read")), "agent-service")
    assert e.value.reason == "missing_scope"


async def test_required_claims_missing_is_malformed(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock, required_claims=("sub", "dept", "clearance"))
    claims = make_claims(clock.now().timestamp())
    del claims["clearance"]
    with pytest.raises(TokenInvalid) as e:
        await v.verify(signer.sign(claims), "agent-service")
    assert e.value.reason == "malformed"


async def test_tampered_signature_and_foreign_key(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock)
    attacker = TestSigner("ES256", "k1")  # cùng kid, khoá khác
    tok = attacker.sign(make_claims(clock.now().timestamp()))
    with pytest.raises(TokenInvalid) as e:
        await v.verify(tok, "agent-service")
    assert e.value.reason == "bad_signature"


async def test_unknown_kid_refetches_once_then_rejects(signer: TestSigner) -> None:
    clock, ep = FakeClock(), FakeJwksEndpoint([signer])
    v = make(ep, clock, min_refetch_s=30)
    stranger = TestSigner("ES256", "zzz")
    tok = stranger.sign(make_claims(clock.now().timestamp()))
    for _ in range(3):
        with pytest.raises(TokenInvalid) as e:
            await v.verify(tok, "agent-service")
        assert e.value.reason == "unknown_kid"
    assert ep.hits == 1  # không bị ép gọi IdP liên tục


async def test_key_rotation_picks_up_new_kid(signer: TestSigner) -> None:
    clock, ep = FakeClock(), FakeJwksEndpoint([signer])
    v = make(ep, clock, min_refetch_s=30)
    now = clock.now().timestamp()
    assert await v.verify(signer.sign(make_claims(now)), "agent-service")
    new = TestSigner("ES256", "k2")
    ep.signers = [signer, new]
    clock.advance(31)
    assert await v.verify(new.sign(make_claims(clock.now().timestamp())), "agent-service")
    assert ep.hits == 2


async def test_jwks_is_cached(signer: TestSigner) -> None:
    clock, ep = FakeClock(), FakeJwksEndpoint([signer])
    v = make(ep, clock)
    tok = signer.sign(make_claims(clock.now().timestamp()))
    for _ in range(3):
        await v.verify(tok, "agent-service")
    assert ep.hits == 1


async def test_jwks_unavailable_is_not_token_invalid(signer: TestSigner) -> None:
    clock, ep = FakeClock(), FakeJwksEndpoint([signer])
    ep.fail = True
    v = make(ep, clock)
    with pytest.raises(TokenServiceUnavailable):
        await v.verify(signer.sign(make_claims(clock.now().timestamp())), "agent-service")


async def test_garbage_and_none_alg_rejected(signer: TestSigner) -> None:
    clock = FakeClock()
    v = make(FakeJwksEndpoint([signer]), clock)
    with pytest.raises(TokenInvalid) as e:
        await v.verify("not-a-jwt", "agent-service")
    assert e.value.reason == "malformed"
    # token ký HS256 không được chấp nhận
    tok = jwt.encode({"exp": 9999999999}, "x" * 32, algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(TokenInvalid) as e:
        await v.verify(tok, "agent-service")
    assert e.value.reason == "bad_algorithm"
