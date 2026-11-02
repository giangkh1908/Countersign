"""Dựng service + tool + khoá ES256 cho test (không cần Postgres/Redis thật)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import fakeredis
import jwt
from acme_common.adapters.approval_es256_jwt import Es256JwtApprovalVerifier
from acme_common.adapters.intent_es256_jws import Es256JwsIntentIssuer
from acme_common.adapters.replay_memory import InMemoryReplayGuard
from acme_common.mcp import ToolInvoker
from acme_common.mcp.context import AuthContext, reset_auth, set_auth
from acme_common.ports import Principal
from acme_common.testing import FakeClock, FakeEventSink, FakeRateLimiter, FakeToolServerHost
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mcp_tickets.services.ticket_service import TicketService
from mcp_tickets.testing import FakeTicketRepository, make_ticket
from mcp_tickets.tools import register_tools

INTENT_PREFIX = "mcp:tickets:intent:"
START = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
ASSIGNEE = "u-agent"
REQUESTER = "u-req"
OTHER = "u-other"


def principal(
    sub: str = ASSIGNEE,
    *,
    dept: tuple[str, ...] = ("SALES",),
    roles: tuple[str, ...] = ("employee", "team_lead"),
    scopes: tuple[str, ...] = ("tickets:read", "tickets:write"),
) -> Principal:
    return Principal(
        sub=sub,
        audience=("tickets-mcp",),
        azp="agent-service",
        scopes=frozenset(scopes),
        expires_at=time.time() + 3600,
        dept=dept,
        clearance=1,
        roles=roles,
    )


def new_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def pem_private(k: ec.EllipticCurvePrivateKey) -> bytes:
    return k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def pem_public(k: ec.EllipticCurvePrivateKey) -> bytes:
    return k.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


class Env:
    """Toàn bộ phụ thuộc là fake/in-memory; `call()` đặt contextvar auth như `AuthMiddleware`."""

    def __init__(self, *, taint_policy: str = "warn", repo: FakeTicketRepository | None = None):
        self.clock = FakeClock(START)
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.intent_key = new_key()
        self.approval_key = new_key()
        self.repo = repo or FakeTicketRepository(self.clock, [make_ticket()])
        self.issuer = Es256JwsIntentIssuer(
            self.redis,
            private_key_pem=pem_private(self.intent_key),
            key_id="tickets-mcp-1",
            clock=self.clock,
            issuer="tickets-mcp",
            redis_prefix=INTENT_PREFIX,
        )
        self.verifier = Es256JwtApprovalVerifier(
            {"ap-1": self.approval_key.public_key()}, self.clock
        )
        self.replay = InMemoryReplayGuard(self.clock)
        self.service = TicketService(
            self.repo,
            self.issuer,
            self.verifier,
            self.replay,
            self.clock,
            self.redis,
            taint_policy=taint_policy,
        )
        self.sink = FakeEventSink()
        self.host = FakeToolServerHost()
        invoker = ToolInvoker(
            server="tickets-mcp",
            limiter=FakeRateLimiter(),
            audit=self.sink,
            clock=self.clock,
            audit_sync=False,
        )
        register_tools(self.host, invoker, self.service)

    async def call(
        self,
        name: str,
        args: dict[str, Any],
        who: Principal | None = None,
        thread_id: str | None = "T1",
    ) -> tuple[bool, dict[str, Any]]:
        meta = {"io.acme/thread_id": thread_id} if thread_id else {}
        tok = set_auth(AuthContext(who or principal(), str(uuid.uuid4())))
        try:
            res = await self.host.call(name, args, meta)
        finally:
            reset_auth(tok)
        return res.is_error, dict(res.data)

    def approval(
        self,
        intent: dict[str, Any],
        *,
        sub: str = ASSIGNEE,
        jti: str | None = None,
        sha: str | None = None,
        ttl: int = 120,
        key: ec.EllipticCurvePrivateKey | None = None,
        aud: str = "tickets-mcp",
    ) -> tuple[str, str]:
        """Ký approval đúng định dạng của approval-signer. Trả `(token, jti)`."""
        now = int(self.clock.now().timestamp())
        jti = jti or str(uuid.uuid4())
        claims = {
            "iss": "acme-approval",
            "aud": aud,
            "sub": sub,
            "intent_id": intent["intent_id"],
            "intent_sha256": sha or self.sha_of(intent),
            "jti": jti,
            "iat": now,
            "exp": now + ttl,
        }
        token = jwt.encode(
            claims,
            key or self.approval_key,
            algorithm="ES256",
            headers={"typ": "acme-approval+jwt", "kid": "ap-1"},
        )
        return token, jti

    @staticmethod
    def sha_of(intent: dict[str, Any]) -> str:
        from acme_common.services.canonical import intent_sha256

        payload = jwt.decode(intent["intent_jws"], options={"verify_signature": False})
        return intent_sha256(payload)
