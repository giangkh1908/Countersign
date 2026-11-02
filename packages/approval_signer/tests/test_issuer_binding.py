"""Gắn khoá và op với issuer: MCP bị chiếm không mạo danh được MCP khác (actions-roles.md §4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jwt
import pytest
from acme_common.ports import Principal
from acme_common.testing import FakeClock, TestSigner
from approval_signer import rendering
from approval_signer.adapters.es256_jws import Es256JwsIntentVerifier
from approval_signer.ports import SignerError
from cryptography.hazmat.primitives import serialization

SUB = "user-1"
KID = "k-1"


@pytest.fixture(autouse=True)
def _second_issuer(monkeypatch) -> None:
    """Giả lập một MCP ghi thứ hai chỉ sở hữu op `ping` (chưa có thật; chỉ để thử cơ chế)."""
    monkeypatch.setitem(rendering.ISSUER_OPS, "other-mcp", frozenset({"ping"}))


def pub(k: TestSigner) -> bytes:
    return k._key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def payload(clock: FakeClock, iss: str, op: str) -> dict[str, Any]:
    now = int(clock.now().timestamp())
    args = {"code": "TCK-000123", "resolution": "Đã xử lý xong ticket."}
    return {
        "v": 1, "iss": iss, "aud": "approval-signer", "sub": SUB, "iat": now, "exp": now + 300,
        "intent_id": "0194c1e2-7b3a-7d10-9a4e-3f6f2f0b9c11", "op": op,
        "target": {"ticket_code": "TCK-000123"},
        "before": {"status": "open"}, "after": {"status": "closed", "resolution": args["resolution"]},
        "args_canonical": json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        "risk_flags": [],
    }  # fmt: skip


def sign(key: TestSigner, pl: dict[str, Any]) -> str:
    return jwt.encode(
        pl, key._key, algorithm="ES256", headers={"typ": "acme-intent+jws", "kid": KID}
    )


def who() -> Principal:
    return Principal(SUB, ("approval-signer",), "chat-ui", frozenset(), 9e12)


@pytest.fixture
def setup(tmp_path: Path):
    clock = FakeClock()
    tk, other = TestSigner("ES256", KID), TestSigner("ES256", KID)  # cùng kid, khoá khác
    for iss, key in (("tickets-mcp", tk), ("other-mcp", other)):
        (tmp_path / iss).mkdir()
        (tmp_path / iss / f"{KID}.pem").write_bytes(pub(key))
    v = Es256JwsIntentVerifier(tmp_path, clock, issuers=["tickets-mcp", "other-mcp"])
    return clock, tk, other, v


def reason(jws: str, v: Es256JwsIntentVerifier) -> str:
    with pytest.raises(SignerError) as e:
        v.verify_intent(jws, who())
    assert e.value.code == "intent_mismatch"
    return e.value.details["reason"]


def test_each_issuer_verifies_with_its_own_key_and_ops(setup) -> None:
    clock, tk, other, v = setup
    assert (
        v.verify_intent(sign(tk, payload(clock, "tickets-mcp", "close_ticket")), who()).iss
        == "tickets-mcp"
    )
    assert (
        v.verify_intent(sign(other, payload(clock, "other-mcp", "ping")), who()).iss == "other-mcp"
    )


def test_compromised_mcp_cannot_impersonate_another_issuer(setup) -> None:
    clock, tk, other, v = setup
    # tickets-mcp ký bằng khoá của mình nhưng khai iss=other-mcp
    assert reason(sign(tk, payload(clock, "other-mcp", "ping")), v) == "signature"
    # và ngược lại
    assert reason(sign(other, payload(clock, "tickets-mcp", "close_ticket")), v) == "signature"


def test_op_must_belong_to_issuer(setup) -> None:
    clock, tk, other, v = setup
    assert reason(sign(tk, payload(clock, "tickets-mcp", "ping")), v) == "op"
    assert reason(sign(other, payload(clock, "other-mcp", "close_ticket")), v) == "op"
    assert reason(sign(tk, payload(clock, "tickets-mcp", "delete_everything")), v) == "op"


def test_issuer_not_in_trusted_list_or_without_key_dir(setup, tmp_path) -> None:
    clock, tk, other, _ = setup
    only_tickets = Es256JwsIntentVerifier(tmp_path, clock, issuers=["tickets-mcp"])
    assert reason(sign(other, payload(clock, "other-mcp", "ping")), only_tickets) == "iss"
    # khoá đặt thẳng ở gốc thư mục (bố cục cũ, không gắn issuer) không còn được tin
    (tmp_path / "flat").mkdir()
    (tmp_path / "flat" / f"{KID}.pem").write_bytes(pub(tk))
    flat = Es256JwsIntentVerifier(tmp_path / "flat", clock)
    assert reason(sign(tk, payload(clock, "tickets-mcp", "close_ticket")), flat) == "kid"


def test_unsupported_issuer_config_fails_fast(tmp_path) -> None:
    with pytest.raises(ValueError):
        Es256JwsIntentVerifier(tmp_path, FakeClock(), issuers=["nobody-mcp"])
    with pytest.raises(ValueError):
        Es256JwsIntentVerifier(tmp_path, FakeClock(), issuers=[])
