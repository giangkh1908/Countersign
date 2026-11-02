"""Tạo ticket với approval-signer THẬT: thẻ phủ mọi trường args, signer ký, tickets-mcp commit."""

from __future__ import annotations

import pytest
from tickets_harness import Env, pem_private, pem_public, principal

pytest.importorskip("approval_signer")

from approval_signer.adapters.es256_jws import Es256JwsIntentVerifier  # noqa: E402
from approval_signer.adapters.es256_jwt import Es256JwtApprovalSigner  # noqa: E402

ARGS = {
    "title": "Cần cấp tài khoản VPN",
    "body": "Nhân viên mới bắt đầu thứ Hai.",
    "category": "account_access",
    "assignee_dept": "HR",
}


async def test_real_signer_roundtrip_create_ticket(tmp_path) -> None:
    env = Env()
    keys = tmp_path / "intent-keys"
    (keys / "tickets-mcp").mkdir(parents=True)
    (keys / "tickets-mcp" / "tickets-mcp-1.pem").write_bytes(pem_public(env.intent_key))
    err, out = await env.call("prepare_create_ticket", ARGS)
    assert not err, out
    who = principal()
    verifier = Es256JwsIntentVerifier(keys, env.clock)
    model = verifier.verify(out["intent_jws"], who)  # không intent_unrenderable
    assert model.op == "create_ticket" and model.display["title"] == "Tạo ticket mới"
    shown = {f["path"] for f in model.display["display_fields"]}
    assert {"args.title", "args.body", "args.classification", "after.status"} <= shown
    verified = verifier.verify_intent(out["intent_jws"], who)
    signer = Es256JwtApprovalSigner(pem_private(env.approval_key), "ap-1", env.clock)
    approval = signer.sign(verified, who)
    err, res = await env.call(
        "commit_intent", {"intent_id": out["intent_id"], "approval_token": approval.token}
    )
    assert not err, res
    assert res["op"] == "create_ticket" and res["ticket"]["status"] == "open"
    assert res["ticket"]["code"] in env.repo.tickets
