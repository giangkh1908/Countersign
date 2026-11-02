"""Khớp định dạng với approval-signer THẬT: intent do tickets-mcp ký => signer verify/render/ký approval
=> tickets-mcp verify approval và commit. Bỏ qua nếu không cài approval_signer."""

from __future__ import annotations

import pytest
from tickets_harness import ASSIGNEE, Env, principal

pytest.importorskip("approval_signer")

from approval_signer.adapters.es256_jws import Es256JwsIntentVerifier  # noqa: E402
from approval_signer.adapters.es256_jwt import Es256JwtApprovalSigner  # noqa: E402

CLOSE = {"code": "TCK-000123", "resolution": "Đã thay mực và cài lại driver máy in."}


async def test_real_signer_roundtrip(tmp_path) -> None:
    from tickets_harness import pem_private, pem_public

    env = Env()
    keys = tmp_path / "intent-keys"
    (keys / "tickets-mcp").mkdir(parents=True)
    (keys / "tickets-mcp" / "tickets-mcp-1.pem").write_bytes(pem_public(env.intent_key))
    err, out = await env.call("prepare_close_ticket", CLOSE)
    assert not err

    who = principal()
    verifier = Es256JwsIntentVerifier(keys, env.clock)
    verified = verifier.verify_intent(out["intent_jws"], who)
    assert verified.intent_id == out["intent_id"]
    assert verified.sha256 == env.sha_of(out)  # cùng hàm băm ở hai phía
    model = verifier.verify(out["intent_jws"], who)  # render được: không có trường lạ
    assert model.op == "close_ticket" and model.display["risk"] == "medium"
    assert [d["field"] for d in model.display["diff"]] == ["resolution", "status"]

    signer = Es256JwtApprovalSigner(pem_private(env.approval_key), "ap-1", env.clock)
    approval = signer.sign(verified, who)
    err, res = await env.call(
        "commit_intent",
        {"intent_id": out["intent_id"], "approval_token": approval.token, "args": CLOSE},
    )
    assert not err, res
    assert res["approval_jti"] == approval.jti and res["ticket"]["status"] == "closed"
    assert env.repo.events[0].actor_sub == ASSIGNEE
