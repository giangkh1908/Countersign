import pytest
from acme_common import factory
from acme_common.caching_token_broker import CachingTokenBroker
from acme_common.ports import (
    AnchorStore,
    AnchorStoreNotConfigured,
    Clock,
    ClockNotConfigured,
    EventSink,
    EventSinkNotConfigured,
    RateLimiter,
    RateLimiterNotConfigured,
    TokenBroker,
    TokenBrokerNotConfigured,
    TokenVerifier,
    TokenVerifierNotConfigured,
)
from acme_common.settings import CommonSettings
from acme_common.testing import FakeClock

S = CommonSettings()
CLOCK = FakeClock()


@pytest.mark.parametrize("name", ["system", "fake"])
def test_build_clock(name: str) -> None:
    assert isinstance(factory.build_clock(name, S), Clock)


def test_build_clock_unknown() -> None:
    with pytest.raises(ClockNotConfigured, match=r"known: \['fake', 'system'\]"):
        factory.build_clock("nope", S)


def test_build_token_verifier() -> None:
    assert isinstance(factory.build_token_verifier("oidc_jwks", S, clock=CLOCK), TokenVerifier)


def test_build_token_verifier_unknown() -> None:
    with pytest.raises(TokenVerifierNotConfigured, match="oidc_jwks"):
        factory.build_token_verifier("nope", S, clock=CLOCK)


def test_build_token_broker_wraps_with_cache() -> None:
    b = factory.build_token_broker(
        "oauth_token_exchange", S, clock=CLOCK, client_id="c", client_secret="s"
    )
    assert isinstance(b, TokenBroker) and isinstance(b, CachingTokenBroker)
    raw = factory.build_token_broker("static", S, clock=CLOCK, cache=False)
    assert isinstance(raw, TokenBroker) and not isinstance(raw, CachingTokenBroker)


def test_build_token_broker_unknown() -> None:
    with pytest.raises(TokenBrokerNotConfigured, match="oauth_token_exchange"):
        factory.build_token_broker("nope", S, clock=CLOCK)


@pytest.mark.parametrize("name", ["json_log", "postgres"])
def test_build_event_sink(name: str) -> None:
    assert isinstance(factory.build_event_sink(name, S), EventSink)


def test_build_event_sink_unknown() -> None:
    with pytest.raises(EventSinkNotConfigured, match="json_log"):
        factory.build_event_sink("nope", S)


@pytest.mark.parametrize("name", ["in_memory", "redis_token_bucket"])
def test_build_rate_limiter(name: str) -> None:
    assert isinstance(factory.build_rate_limiter(name, S, clock=CLOCK), RateLimiter)


def test_build_rate_limiter_unknown() -> None:
    with pytest.raises(RateLimiterNotConfigured, match="in_memory"):
        factory.build_rate_limiter("nope", S, clock=CLOCK)


def test_build_anchor_store(tmp_path) -> None:
    s = CommonSettings(audit_anchor_dir=str(tmp_path))
    assert isinstance(factory.build_anchor_store("file_append_only", s), AnchorStore)


def test_build_anchor_store_unknown() -> None:
    with pytest.raises(AnchorStoreNotConfigured, match="file_append_only"):
        factory.build_anchor_store("nope", S)


async def test_m2_stubs_fail_loudly() -> None:
    with pytest.raises(NotImplementedError):
        factory.build_event_sink("postgres", S).append({"x": 1})
    with pytest.raises(NotImplementedError):
        await factory.build_rate_limiter("redis_token_bucket", S, clock=CLOCK).release_slot("k")
