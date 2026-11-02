"""`IntentCommitService` dùng được cho MCP ghi khác ticket (notify-mcp sau này): executor giả, không có ticket."""

from __future__ import annotations

import time
import uuid
from typing import Any

import fakeredis
import jwt
import pytest
from acme_common.adapters.approval_es256_jwt import Es256JwtApprovalVerifier
from acme_common.adapters.intent_es256_jws import Es256JwsIntentIssuer
from acme_common.adapters.replay_memory import InMemoryReplayGuard
from acme_common.mcp.errors import ToolError
from acme_common.ports import (
    Approval,
    Draft,
    DuplicateIntent,
    ExecutionRolledBack,
    ExecutionUnavailable,
    Intent,
    IntentExecutor,
    Principal,
)
from acme_common.services.canonical import intent_sha256
from acme_common.services.intent_commit import IntentCommitService
from acme_common.testing import FakeClock
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

PREFIX = "mcp:demo:intent:"


class DemoExecutor(IntentExecutor):
    def __init__(self) -> None:
        self.sent: list[Intent] = []
        self.allowed = True
        self.raise_on_execute: Exception | None = None

    async def reauthorize(self, principal: Principal, intent: Intent) -> None:
        if not self.allowed:
            raise ToolError("forbidden", "not allowed")

    async def execute(self, intent: Intent, approval: Approval, principal: Principal) -> Any:
        if self.raise_on_execute:
            raise self.raise_on_execute
        if any(i.intent_id == intent.intent_id for i in self.sent):
            raise DuplicateIntent
        self.sent.append(intent)
        return {"sent": intent.args["text"]}

    async def applied_details(self, intent_id: str, principal: Principal) -> dict[str, Any] | None:
        return (
            {"already_applied": True} if any(i.intent_id == intent_id for i in self.sent) else None
        )


def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def pem(k: ec.EllipticCurvePrivateKey) -> bytes:
    return k.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


class Rig:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.ap_key = key()
        self.exec = DemoExecutor()
        self.issuer = Es256JwsIntentIssuer(
            self.redis, private_key_pem=pem(key()), key_id="demo-1", clock=self.clock,
            issuer="demo-mcp", redis_prefix=PREFIX,
        )  # fmt: skip
        self.svc = IntentCommitService(
            self.issuer,
            Es256JwtApprovalVerifier(
                {"ap-1": self.ap_key.public_key()}, self.clock, audience="demo-mcp"
            ),
            InMemoryReplayGuard(self.clock),
            self.clock,
            self.exec,
        )
        self.who = Principal("u1", ("demo-mcp",), "agent-service", frozenset(), time.time() + 3600)

    async def prepare(self) -> Any:
        draft = Draft({"group": "g"}, {}, {"text": "xin chào"}, None)
        return await self.issuer.issue("send_demo", {"text": "xin chào"}, self.who, draft)

    def approval(self, s: Any, *, jti: str | None = None, ttl: int = 120) -> str:
        now = int(self.clock.now().timestamp())
        claims = {
            "iss": "acme-approval", "aud": "demo-mcp", "sub": "u1", "intent_id": s.intent_id,
            "intent_sha256": intent_sha256(s.payload), "jti": jti or str(uuid.uuid4()),
            "iat": now, "exp": now + ttl,
        }  # fmt: skip
        return jwt.encode(
            claims, self.ap_key, "ES256", headers={"typ": "acme-approval+jwt", "kid": "ap-1"}
        )


async def code_of(coro: Any) -> str:
    with pytest.raises(ToolError) as e:
        await coro
    return e.value.code


async def test_happy_path_then_replay() -> None:
    r = Rig()
    s = await r.prepare()
    tok = r.approval(s)
    assert await r.svc.commit(r.who, s.intent_id, tok) == {"sent": "xin chào"}
    assert r.exec.sent[0].target == {"group": "g"} and r.exec.sent[0].ticket_code is None
    assert await code_of(r.svc.commit(r.who, s.intent_id, tok)) == "approval_replayed"
    assert await code_of(r.svc.commit(r.who, s.intent_id, r.approval(s))) == "approval_replayed"
    assert len(r.exec.sent) == 1


async def test_denied_by_executor_writes_nothing_and_keeps_jti() -> None:
    r = Rig()
    s = await r.prepare()
    r.exec.allowed = False
    tok = r.approval(s, jti="11111111-1111-4111-8111-111111111111")
    assert await code_of(r.svc.commit(r.who, s.intent_id, tok)) == "forbidden"
    assert r.exec.sent == []
    r.exec.allowed = True
    assert await r.svc.commit(r.who, s.intent_id, tok)  # jti chưa bị đốt


async def test_expiry_signature_and_args_checks_hold() -> None:
    r = Rig()
    s = await r.prepare()
    assert await code_of(r.svc.commit(r.who, s.intent_id, "")) == "approval_required"
    forged = jwt.encode(
        {"x": 1}, key(), "ES256", headers={"typ": "acme-approval+jwt", "kid": "ap-1"}
    )
    assert await code_of(r.svc.commit(r.who, s.intent_id, forged)) == "approval_invalid"
    tok = r.approval(s)
    assert (
        await code_of(r.svc.commit(r.who, s.intent_id, tok, {"text": "khác"})) == "intent_mismatch"
    )
    r.clock.advance(121)
    assert await code_of(r.svc.commit(r.who, s.intent_id, tok)) == "approval_expired"
    r.clock.advance(400)
    assert await code_of(r.svc.commit(r.who, s.intent_id, r.approval(s))) in (
        "intent_expired",
        "intent_not_found",
    )
    assert r.exec.sent == []


async def test_rollback_fails_intent_and_unknown_outcome_stays_committing() -> None:
    r = Rig()
    s = await r.prepare()
    r.exec.raise_on_execute = ExecutionRolledBack()
    assert await code_of(r.svc.commit(r.who, s.intent_id, r.approval(s))) == "upstream_unavailable"
    assert await code_of(r.svc.commit(r.who, s.intent_id, r.approval(s))) == "intent_mismatch"
    s2 = await r.prepare()
    r.exec.raise_on_execute = ExecutionUnavailable()
    assert (
        await code_of(r.svc.commit(r.who, s2.intent_id, r.approval(s2))) == "upstream_unavailable"
    )
    assert await r.redis.hget(PREFIX + s2.intent_id, "status") == "committing"
