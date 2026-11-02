"""Dựng service + tool + khoá ES256 cho test (không cần Postgres/Redis/Telegram thật)."""

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
from acme_common.services.taint import raise_taint
from acme_common.testing import FakeClock, FakeEventSink, FakeRateLimiter, FakeToolServerHost
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mcp_notify.adapters.fake import FakeMessageChannel
from mcp_notify.channels import ChannelConfig
from mcp_notify.services.report_service import NotifyService
from mcp_notify.testing import FakeDeliveryLog
from mcp_notify.tools import register_tools

INTENT_PREFIX = "mcp:notify:intent:"
START = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
LEAD = "u-lead"

CHANNELS = {
    "dept-eng": ChannelConfig("dept-eng", "fake", "TG_CHAT_ENG", "dept", "ENG", 1),
    "dept-sales": ChannelConfig("dept-sales", "fake", "TG_CHAT_SALES", "dept", "SALES", 0),
    "company-all": ChannelConfig("company-all", "fake", "TG_CHAT_ALL", "company", None, 0),
}


def principal(
    sub: str = LEAD,
    *,
    dept: tuple[str, ...] = ("ENG",),
    roles: tuple[str, ...] = ("employee", "team_lead"),
    scopes: tuple[str, ...] = ("notify:write",),
) -> Principal:
    return Principal(
        sub=sub,
        audience=("notify-mcp",),
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
    def __init__(self) -> None:
        self.clock = FakeClock(START)
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.intent_key = new_key()
        self.approval_key = new_key()
        self.sender = FakeMessageChannel()
        self.deliveries = FakeDeliveryLog()
        self.issuer = Es256JwsIntentIssuer(
            self.redis,
            private_key_pem=pem_private(self.intent_key),
            key_id="notify-mcp-1",
            clock=self.clock,
            issuer="notify-mcp",
            redis_prefix=INTENT_PREFIX,
        )
        self.verifier = Es256JwtApprovalVerifier(
            {"ap-1": self.approval_key.public_key()}, self.clock, audience="notify-mcp"
        )
        self.service = NotifyService(
            CHANNELS,
            {"fake": self.sender},
            self.deliveries,
            self.issuer,
            self.verifier,
            InMemoryReplayGuard(self.clock),
            self.clock,
            self.redis,
        )
        self.sink = FakeEventSink()
        self.host = FakeToolServerHost()
        invoker = ToolInvoker(
            server="notify-mcp",
            limiter=FakeRateLimiter(),
            audit=self.sink,
            clock=self.clock,
            audit_sync=False,
        )
        register_tools(self.host, invoker, self.service)

    async def taint(self, sub: str, max_class: int, thread: str | None = "T1") -> None:
        assert await raise_taint(self.redis, sub, thread, max_class, {"ENG"}, "doc-1")

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
        sub: str = LEAD,
        jti: str | None = None,
        ttl: int = 120,
        aud: str = "notify-mcp",
    ) -> tuple[str, str]:
        now = int(self.clock.now().timestamp())
        jti = jti or str(uuid.uuid4())
        claims = {
            "iss": "acme-approval",
            "aud": aud,
            "sub": sub,
            "intent_id": intent["intent_id"],
            "intent_sha256": self.sha_of(intent),
            "jti": jti,
            "iat": now,
            "exp": now + ttl,
        }
        token = jwt.encode(
            claims,
            self.approval_key,
            algorithm="ES256",
            headers={"typ": "acme-approval+jwt", "kid": "ap-1"},
        )
        return token, jti

    @staticmethod
    def sha_of(intent: dict[str, Any]) -> str:
        from acme_common.services.canonical import intent_sha256

        payload = jwt.decode(intent["intent_jws"], options={"verify_signature": False})
        return intent_sha256(payload)

    async def prepare(
        self, channel: str = "dept-eng", text: str = "Báo cáo tuần: doanh thu tăng.", **kw: Any
    ) -> dict[str, Any]:
        who = kw.pop("who", None)
        err, out = await self.call(
            "prepare_send_group_report", {"channel": channel, "text": text, **kw}, who
        )
        assert not err, out
        return out

    async def commit(
        self, out: dict[str, Any], who: Principal | None = None, **kw: Any
    ) -> tuple[bool, dict[str, Any], str]:
        token, jti = self.approval(out, sub=(who or principal()).sub, **kw)
        err, res = await self.call(
            "commit_intent", {"intent_id": out["intent_id"], "approval_token": token}, who
        )
        return err, res, jti
