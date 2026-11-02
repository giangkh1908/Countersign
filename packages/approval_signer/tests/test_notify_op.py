"""Op `send_group_report` của notify-mcp: render thẻ duyệt và gắn op với issuer (actions-roles.md §4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from acme_common.ports import Principal
from acme_common.testing import FakeClock, TestSigner
from approval_signer.adapters.es256_jws import Es256JwsIntentVerifier
from approval_signer.ports import SignerError, VerifiedIntent
from approval_signer.rendering import build_render_model
from cryptography.hazmat.primitives import serialization

SUB = "user-1"
KID = "notify-mcp-1"
TEXT = "Báo cáo tuần:\ndoanh thu tăng 5%.\u202e"


def payload(now: int, iss: str = "notify-mcp", op: str = "send_group_report", **over: Any) -> dict:
    args = {"channel": "dept-eng", "text": TEXT}
    p = {
        "v": 1, "iss": iss, "aud": "approval-signer", "sub": SUB, "iat": now, "exp": now + 300,
        "intent_id": "0194c1e2-7b3a-7d10-9a4e-3f6f2f0b9c11", "op": op,
        "target": {"channel": "dept-eng"}, "before": {}, "after": {"text": TEXT},
        "args_canonical": json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        "risk_flags": [],
    }  # fmt: skip
    p.update(over)
    return p


def model(**over: Any):
    now = 1_800_000_000
    return build_render_model(
        VerifiedIntent(payload(now, **over), "h" * 64),
        datetime.fromtimestamp(now, UTC),
    )


def test_render_report_card() -> None:
    m = model()
    assert m.display["title"] == "Gửi báo cáo tới nhóm dept-eng"
    assert m.display["risk"] == "medium"
    paths = {f["path"] for f in m.display["display_fields"]}
    assert paths == {"target.channel", "args.channel", "args.text", "after.text"}
    text_field = next(f for f in m.display["display_fields"] if f["path"] == "args.text")
    assert "\n" in text_field["after"] and "\\u202e" in text_field["after"]  # bidi bị escape
    assert m.display["diff"] == [{"field": "text", "before": None, "after": text_field["after"]}]


def test_risk_flags_pass_through() -> None:
    assert model(risk_flags=["unverified_claims"]).risk_flags == ["unverified_claims"]
    assert model(risk="high").display["risk"] == "high"


@pytest.mark.parametrize(
    "over",
    [
        {"target": {}},
        {"target": {"ticket_code": "TCK-000123"}},
        {"target": {"channel": "dept-eng", "title": "x"}},
        {"after": {"text": TEXT, "extra": "x"}},
        {"after": {}},
        {"args_canonical": json.dumps({"channel": "dept-eng", "text": TEXT, "parse_mode": "HTML"})},
    ],
)
def test_unrenderable(over) -> None:
    with pytest.raises(SignerError) as e:
        model(**over)
    assert e.value.code == "intent_unrenderable"


def test_ticket_ops_still_require_ticket_code() -> None:
    with pytest.raises(SignerError):
        model(
            iss="tickets-mcp",
            op="close_ticket",
            target={"channel": "dept-eng"},
        )


# ---------------------------------------------------------------- gắn op với issuer
def pub(k: TestSigner) -> bytes:
    return k._key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def sign(key: TestSigner, pl: dict[str, Any]) -> str:
    return jwt.encode(
        pl, key._key, algorithm="ES256", headers={"typ": "acme-intent+jws", "kid": KID}
    )


@pytest.fixture
def setup(tmp_path: Path):
    clock = FakeClock()
    tk, nk = TestSigner("ES256", KID), TestSigner("ES256", KID)
    for iss, key in (("tickets-mcp", tk), ("notify-mcp", nk)):
        (tmp_path / iss).mkdir()
        (tmp_path / iss / f"{KID}.pem").write_bytes(pub(key))
    v = Es256JwsIntentVerifier(tmp_path, clock, issuers=["tickets-mcp", "notify-mcp"])
    return int(clock.now().timestamp()), tk, nk, v


def who() -> Principal:
    return Principal(SUB, ("approval-signer",), "chat-ui", frozenset(), 9e12)


def reason(jws: str, v: Es256JwsIntentVerifier) -> str:
    with pytest.raises(SignerError) as e:
        v.verify_intent(jws, who())
    assert e.value.code == "intent_mismatch"
    return e.value.details["reason"]


def test_notify_issues_send_group_report(setup) -> None:
    now, _, nk, v = setup
    assert v.verify_intent(sign(nk, payload(now)), who()).iss == "notify-mcp"


def test_tickets_mcp_cannot_issue_send_group_report(setup) -> None:
    now, tk, _, v = setup
    assert reason(sign(tk, payload(now, iss="tickets-mcp")), v) == "op"
    assert reason(sign(tk, payload(now)), v) == "signature"  # mạo danh iss=notify-mcp


def test_notify_cannot_issue_ticket_ops_or_be_impersonated(setup) -> None:
    now, tk, nk, v = setup
    assert reason(sign(nk, payload(now, op="close_ticket")), v) == "op"
    assert reason(sign(nk, payload(now, iss="tickets-mcp", op="close_ticket")), v) == "signature"


def test_approval_audience_follows_issuer() -> None:
    from approval_signer.adapters.es256_jwt import _AUD_BY_INTENT_ISS

    assert _AUD_BY_INTENT_ISS == {"tickets-mcp": "tickets-mcp", "notify-mcp": "notify-mcp"}
