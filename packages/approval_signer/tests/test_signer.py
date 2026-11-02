from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
import pytest
from acme_common.ports import Principal, TokenServiceUnavailable
from acme_common.services.canonical import intent_sha256
from acme_common.testing import FakeClock, FakeRateLimiter, FakeTokenVerifier, TestSigner
from approval_signer.adapters.es256_jws import Es256JwsIntentVerifier
from approval_signer.adapters.es256_jwt import Es256JwtApprovalSigner
from approval_signer.api import Deps, create_app
from approval_signer.approval import ApprovalService
from approval_signer.factory import build_approval_signer, build_intent_verifier
from approval_signer.ports import (
    ApprovalSignerNotConfigured,
    IntentVerifierNotConfigured,
    SignerError,
)
from approval_signer.rendering import escape_text
from approval_signer.settings import Settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

INTENT_KID = "tickets-mcp-1"
APPROVAL_KID = "ap-1"
USER = "user-1"


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch) -> None:
    """Chạy trong thư mục trống để `.env` thật ở gốc repo không lọt vào Settings."""
    monkeypatch.chdir(tmp_path)


def principal(
    sub: str = USER, *, aud=("approval-signer",), azp: str | None = "chat-ui"
) -> Principal:
    return Principal(
        sub=sub, audience=tuple(aud), azp=azp, scopes=frozenset({"signer:approve"}), expires_at=9e12
    )


def close_payload(now: float, **over: Any) -> dict[str, Any]:
    args = {"code": "TCK-000123", "resolution": "Đã thay mực và cài lại driver máy in."}
    p: dict[str, Any] = {
        "v": 1,
        "iss": "tickets-mcp",
        "aud": "approval-signer",
        "sub": USER,
        "iat": int(now),
        "exp": int(now) + 300,
        "intent_id": "0194c1e2-7b3a-7d10-9a4e-3f6f2f0b9c11",
        "op": "close_ticket",
        "target": {"ticket_code": "TCK-000123"},
        "before": {"status": "in_progress", "resolution": None, "title": "Máy in tầng 3"},
        "after": {"status": "closed", "resolution": args["resolution"]},
        "expected_updated_at": "2026-10-28T08:12:44Z",
        "args_canonical": json.dumps(
            args, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ),
        "risk": "medium",
        "risk_flags": ["destructive"],
    }
    p.update(over)
    return p


DEL = object()  # sentinel: xoá claim khỏi payload intent


@dataclass
class Env:
    clock: FakeClock
    intent_key: TestSigner
    approval_pub: ec.EllipticCurvePublicKey
    verifier: Es256JwsIntentVerifier
    signer: Es256JwtApprovalSigner
    service: ApprovalService
    tokens: FakeTokenVerifier

    def intent(self, **over: Any) -> str:
        """Intent JWS hợp lệ do 'tickets-mcp' ký; `over` ghi đè claim, khoá giá trị `_DEL` thì xoá."""
        payload = close_payload(self.clock.now().timestamp())
        for k, v in over.items():
            if v is DEL:
                payload.pop(k, None)
            else:
                payload[k] = v
        return jwt.encode(
            payload,
            self.intent_key._key,
            algorithm="ES256",
            headers={"typ": "acme-intent+jws", "kid": INTENT_KID},
        )

    def client(self, *, metrics_token: str | None = None) -> TestClient:
        deps = Deps(self.service, self.tokens, metrics_token=metrics_token)
        return TestClient(create_app(deps), raise_server_exceptions=False)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    clock = FakeClock()
    intent_key = TestSigner("ES256", INTENT_KID)
    keys_dir = tmp_path / "intent-keys"
    (keys_dir / "tickets-mcp").mkdir(parents=True)
    (keys_dir / "tickets-mcp" / f"{INTENT_KID}.pem").write_bytes(
        intent_key._key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    approval_priv = ec.generate_private_key(ec.SECP256R1())
    pem = approval_priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    verifier = Es256JwsIntentVerifier(keys_dir, clock)
    signer = Es256JwtApprovalSigner(pem, APPROVAL_KID, clock, ttl_s=120)
    service = ApprovalService(verifier, signer, FakeRateLimiter(), clock)
    tokens = FakeTokenVerifier({"good": principal()})
    return Env(clock, intent_key, approval_priv.public_key(), verifier, signer, service, tokens)


H = {"Authorization": "Bearer good"}


def code(exc: pytest.ExceptionInfo[SignerError]) -> str:
    return exc.value.code


# --- IntentVerifier (adapter es256_jws) ---
def test_verify_ok_builds_render_model(env: Env) -> None:
    model = env.verifier.verify(env.intent(), principal())
    d = model.to_dict()
    assert d["op"] == "close_ticket"
    assert d["intent_sha256"] and d["server_time"].endswith("Z")
    paths = {f["path"] for f in d["display"]["display_fields"]}
    assert {"target.ticket_code", "args.code", "args.resolution", "after.status"} <= paths
    assert d["display"]["title"] == "Đóng ticket TCK-000123"
    assert {f["kind"] for f in d["display"]["display_fields"]} <= {
        "text", "longtext", "enum", "datetime", "ticket_ref"
    }  # fmt: skip


def test_wrong_sub_rejected(env: Env) -> None:
    with pytest.raises(SignerError) as e:
        env.verifier.verify(env.intent(), principal("someone-else"))
    assert code(e) == "intent_mismatch" and e.value.details["reason"] == "sub"


def test_expired_intent(env: Env) -> None:
    jws = env.intent()
    env.clock.advance(301)
    with pytest.raises(SignerError) as e:
        env.verifier.verify(jws, principal())
    assert code(e) == "intent_expired" and e.value.http_status == 410


def test_bad_signature(env: Env) -> None:
    other = TestSigner("ES256", INTENT_KID)  # cùng kid, khoá khác
    jws = jwt.encode(
        {**json.loads(json.dumps({})), "iss": "tickets-mcp", "aud": "approval-signer"},
        other._key,
        algorithm="ES256",
        headers={"typ": "acme-intent+jws", "kid": INTENT_KID},
    )
    with pytest.raises(SignerError) as e:
        env.verifier.verify(jws, principal())
    assert e.value.details["reason"] == "signature"


@pytest.mark.parametrize(
    ("over", "reason"),
    [({"iss": "evil-mcp"}, "iss"), ({"aud": "tickets-mcp"}, "aud")],
)
def test_bad_iss_aud(env: Env, over: dict, reason: str) -> None:
    with pytest.raises(SignerError) as e:
        env.verifier.verify(env.intent(**over), principal())
    assert e.value.details["reason"] == reason


def test_bad_typ_alg_kid_format(env: Env) -> None:
    good = env.intent()
    payload = jwt.decode(good, options={"verify_signature": False})
    bad_typ = jwt.encode(
        payload, env.intent_key._key, "ES256", headers={"typ": "JWT", "kid": INTENT_KID}
    )
    unknown_kid = jwt.encode(
        payload, env.intent_key._key, "ES256", headers={"typ": "acme-intent+jws", "kid": "nope"}
    )
    traversal = jwt.encode(
        payload, env.intent_key._key, "ES256", headers={"typ": "acme-intent+jws", "kid": "../x"}
    )
    for jws, reason in ((bad_typ, "typ"), (unknown_kid, "kid"), (traversal, "kid")):
        with pytest.raises(SignerError) as e:
            env.verifier.verify(jws, principal())
        assert e.value.details["reason"] == reason
    with pytest.raises(SignerError) as e:
        env.verifier.verify("not-a-jws", principal())
    assert code(e) == "invalid_argument"


@pytest.mark.parametrize(
    "over",
    [
        {"after": DEL},
        {"args_canonical": DEL},
        {"target": {"ticket_code": "TCK-1", "secret": "x"}},  # khoá lạ trong target
        {"after": {"status": "closed", "hidden_flag": True}},  # khoá lạ trong after
        {"args_canonical": json.dumps({"code": "TCK-1", "resolution": "xxxxx", "extra": 1})},
        {"after": {"status": ["closed"]}},  # kiểu không hiển thị được
    ],
)
def test_unrenderable(env: Env, over: dict) -> None:
    with pytest.raises(SignerError) as e:
        env.verifier.verify(env.intent(**over), principal())
    assert code(e) == "intent_unrenderable" and e.value.http_status == 422


def test_bidi_and_control_escaped_in_display_only(env: Env) -> None:
    evil = "ok‮ txt.exe​\x07\n"
    after = {"status": "closed", "resolution": evil}
    jws = env.intent(
        after=after, args_canonical=json.dumps({"code": "TCK-000123", "resolution": evil})
    )
    d = env.verifier.verify(jws, principal()).to_dict()
    shown = json.dumps(d["display"])
    assert "‮" not in shown and "​" not in shown and "\x07" not in shown
    res = next(f for f in d["display"]["display_fields"] if f["path"] == "after.resolution")
    assert res["after"] == "ok\\u202e txt.exe\\u200b\\u0007\n"  # longtext giữ \n
    assert d["after"]["resolution"] == evil  # dữ liệu đã ký giữ nguyên


def test_escape_text() -> None:
    assert escape_text("a⁦b⁩\x00\x85") == "a\\u2066b\\u2069\\u0000\\u0085"
    assert escape_text("a\nb") == "a\\u000ab"
    assert escape_text("a\nb", keep_newlines=True) == "a\nb"
    assert escape_text("Tiếng Việt 😀") == "Tiếng Việt 😀"


# --- ApprovalSigner (adapter es256_jwt) ---
async def test_approval_token_binds_intent_hash(env: Env) -> None:
    jws = env.intent()
    token, _ = await env.service.approve(jws, principal())
    claims = jwt.decode(
        token.token,
        env.approval_pub,
        algorithms=["ES256"],
        audience="tickets-mcp",
        issuer="acme-approval",
        options={"verify_exp": False, "verify_iat": False},  # FakeClock không phải giờ thật
    )
    payload = jwt.decode(jws, options={"verify_signature": False})
    assert claims["intent_sha256"] == intent_sha256(payload)
    assert (
        claims["intent_sha256"]
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    assert claims["sub"] == USER and claims["intent_id"] == payload["intent_id"]
    assert claims["exp"] - claims["iat"] == 120 and claims["jti"] == token.jti
    header = jwt.get_unverified_header(token.token)
    assert header == {"alg": "ES256", "typ": "acme-approval+jwt", "kid": "ap-1"}


async def test_approve_unique_jti_and_no_sign_on_bad_intent(env: Env) -> None:
    a, _ = await env.service.approve(env.intent(), principal())
    b, _ = await env.service.approve(env.intent(), principal())
    assert a.jti != b.jti
    with pytest.raises(SignerError) as e:
        await env.service.approve(env.intent(after=DEL), principal())
    assert code(e) == "intent_unrenderable"


async def test_approval_rate_limited(env: Env) -> None:
    env.service._rate = 2
    for _ in range(2):
        await env.service.approve(env.intent(), principal())
    with pytest.raises(SignerError) as e:
        await env.service.approve(env.intent(), principal())
    assert code(e) == "rate_limited"


# --- HTTP ---
def test_http_verify_and_approve(env: Env) -> None:
    c = env.client()
    r = c.post("/v1/intents/verify", json={"intent_jws": env.intent()}, headers=H)
    assert r.status_code == 200 and r.json()["display"]["display_fields"]
    r = c.post("/v1/approvals", json={"intent_jws": env.intent()}, headers=H)
    body = r.json()
    assert r.status_code == 200 and set(body) == {"approval_token", "jti", "expires_at"}
    assert r.headers["X-Request-Id"]


def test_http_no_or_bad_token(env: Env) -> None:
    c = env.client()
    assert c.post("/v1/approvals", json={"intent_jws": env.intent()}).status_code == 401
    r = c.post(
        "/v1/approvals", json={"intent_jws": env.intent()}, headers={"Authorization": "Bearer x"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_http_agent_token_rejected(env: Env) -> None:
    env.tokens.add("agent", principal(aud=("agent-service",), azp="chat-ui"))
    both = principal(aud=("approval-signer", "agent-service"))
    env.tokens.add("both", both)
    c = env.client()
    for tok in ("agent", "both"):
        r = c.post(
            "/v1/approvals",
            json={"intent_jws": env.intent()},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    env.tokens.add("agent_azp", principal(azp="agent-service"))
    r = c.post(
        "/v1/approvals",
        json={"intent_jws": env.intent()},
        headers={"Authorization": "Bearer agent_azp"},
    )
    assert r.status_code == 403


def test_http_sub_mismatch_and_errors_do_not_leak(env: Env) -> None:
    env.tokens.add("mallory", principal("mallory"))
    r = env.client().post(
        "/v1/approvals",
        json={"intent_jws": env.intent()},
        headers={"Authorization": "Bearer mallory"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "intent_mismatch"
    assert USER not in r.text and "tickets-mcp" not in r.text


def test_http_expired_410_unrenderable_422_invalid_422(env: Env) -> None:
    c = env.client()
    unr = c.post("/v1/intents/verify", json={"intent_jws": env.intent(after=DEL)}, headers=H)
    assert unr.status_code == 422 and unr.json()["error"]["code"] == "intent_unrenderable"
    assert c.post("/v1/intents/verify", json={}, headers=H).status_code == 422
    assert c.post("/v1/intents/verify", content=b"zz", headers=H).status_code == 422
    jws = env.intent()
    env.clock.advance(400)
    r = c.post("/v1/approvals", json={"intent_jws": jws}, headers=H)
    assert r.status_code == 410 and r.json()["error"]["code"] == "intent_expired"


def test_http_idp_down_503(env: Env) -> None:
    class Down(FakeTokenVerifier):
        async def verify(self, token: str, audience: str):  # type: ignore[override]
            raise TokenServiceUnavailable("jwks")

    env.tokens = Down()
    env.service  # noqa: B018
    r = env.client().post("/v1/approvals", json={"intent_jws": "x"}, headers=H)
    assert r.status_code == 503 and r.json()["error"]["retryable"] is True


def test_healthz_and_metrics(env: Env) -> None:
    c = env.client(metrics_token="m-secret")
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/metrics").status_code == 401
    c.post("/v1/approvals", json={"intent_jws": env.intent()}, headers=H)
    r = c.get("/metrics", headers={"Authorization": "Bearer m-secret"})
    assert r.status_code == 200 and 'signer_approval_total{result="ok"} 1' in r.text
    assert env.client().get("/metrics", headers={"Authorization": "Bearer "}).status_code == 401


# --- Factory / settings ---
def test_factory_known_and_unknown(env: Env, tmp_path) -> None:
    s = Settings(
        intent_public_keys_dir=str(tmp_path / "intent-keys"),
        approval_signer_key_id="ap-1",
    )
    v = build_intent_verifier("es256_jws", s, clock=env.clock)
    assert isinstance(v, Es256JwsIntentVerifier)
    with pytest.raises(IntentVerifierNotConfigured) as e:
        build_intent_verifier("permissive", s, clock=env.clock)
    assert "es256_jws" in str(e.value)
    with pytest.raises(ApprovalSignerNotConfigured) as e2:
        build_approval_signer("nope", s, clock=env.clock)
    assert "es256_jwt" in str(e2.value)
    with pytest.raises(ApprovalSignerNotConfigured):  # thiếu khoá => fail-fast
        build_approval_signer("es256_jwt", s, clock=env.clock)


def test_signing_key_from_file_secret(env: Env, tmp_path, monkeypatch) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    f = tmp_path / "k.pem"
    f.write_bytes(pem)
    monkeypatch.setenv("APPROVAL_SIGNER_PRIVATE_KEY_FILE", str(f))
    monkeypatch.setenv("APPROVAL_SIGNER_KEY_ID", "ap-9")
    s = Settings()
    assert build_approval_signer("es256_jwt", s, clock=env.clock) is not None
