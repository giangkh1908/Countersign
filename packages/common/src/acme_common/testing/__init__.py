"""Các `Fake<Port>` kế thừa port (gồm `FakeClock`) cho test nghiệp vụ. Xem docs/design/00-contracts.md §9.1 mục 9."""

from .fakes import (
    FakeClock,
    FakeEventSink,
    FakeRateLimiter,
    FakeTokenBroker,
    FakeTokenVerifier,
    FakeToolServerHost,
)
from .signing import ISSUER, FakeJwksEndpoint, TestSigner, make_claims

__all__ = [
    "ISSUER",
    "FakeClock",
    "FakeEventSink",
    "FakeJwksEndpoint",
    "FakeRateLimiter",
    "FakeTokenBroker",
    "FakeTokenVerifier",
    "FakeToolServerHost",
    "TestSigner",
    "make_claims",
]
