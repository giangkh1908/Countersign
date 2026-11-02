#!/usr/bin/env python3
"""E2E notify-mcp (gửi báo cáo vào nhóm chat) trên stack compose THẬT, không trình duyệt.

Cần: stack đang chạy đủ profile `tickets` + `notify` (kênh khai ở infra/notify/channels.yaml, adapter `fake`
nên không gửi gì ra ngoài). Dùng lại hạ tầng của `close_ticket.py` (client Keycloak dev-only `e2e-test`
tạo qua Admin API và xoá ở cuối trong `finally`, mật khẩu ngẫu nhiên chỉ ở bộ nhớ, hop vào container,
LLM là mock-provider được ép kịch bản).

Hai đường đi, ghi rõ để biết ca nào đi tới đâu:
  * Qua agent như BFF (token đăng nhập -> exchange -> agent /threads, /runs, /resume + approval-signer):
    ca dương tính A (prepare -> thẻ duyệt -> approve -> commit) và replay qua agent.
  * Gọi THẲNG notify-mcp / docs-mcp từ container `agent` (cùng mạng acme_core) bằng token user thật đổi
    qua Keycloak (aud=notify-mcp / docs-mcp, như agent làm): các ca từ chối (kênh tuỳ ý, kênh phòng khác,
    vai trò chặn) và taint. Lý do: dựng taint cần đọc tài liệu mật theo thread, và mock-provider không
    ép được tham số xấu qua prompt; đi thẳng vào MCP là đường kiểm đúng chỗ phân quyền (NotifyService).

Chạy: `bash scripts/e2e-notify.sh`. Tác dụng phụ (dev): đặt lại mật khẩu 5 user test, thêm 1 dòng
`report_deliveries` (kênh fake), ghi taint mức 1-2 cho binh.tran và phuc.cao (hết hạn sau 24 giờ ở `recent`).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import close_ticket as ct  # noqa: E402

R = ct.R
AGENT, SIGNER, MOCK = ct.AGENT, ct.SIGNER, ct.MOCK
NOTIFY_MCP = "http://notify-mcp:8103/mcp"
DOCS_MCP = "http://docs-mcp:8101/mcp"

U_SEND = "hieu.vo"  # ENG, team_lead -> REPORT_DEPT
U_TAINT_DEPT = "binh.tran"  # SALES, team_lead, clearance 2 -> đọc được báo cáo doanh số (mức 2)
U_TAINT_ALL = "phuc.cao"  # management -> REPORT_COMPANY; kênh company-all (max_class 0)
U_ADMIN = "oanh.ly"  # employee + admin (WRITE_BLOCKING)
U_AUDITOR = "quynh.dinh"  # auditor (WRITE_BLOCKING)
USERS = [U_SEND, U_TAINT_DEPT, U_TAINT_ALL, U_ADMIN, U_AUDITOR]
CH_ENG, CH_SALES, CH_ALL = "dept-eng", "dept-sales", "company-all"


# ----------------------------------------------------------------------------- MCP trực tiếp
def mcp(
    url: str, token: str, tool: str, args: dict[str, Any], thread_id: str | None = None
) -> dict[str, Any]:
    """Gọi tool MCP từ container agent. Trả {"is_error", "data"} hoặc {"transport_error"}."""
    req = {
        "token": token,
        "url": url,
        "tool": tool,
        "args": args,
        "meta": {"io.acme/thread_id": thread_id} if thread_id else None,
    }
    p = ct.compose(
        "exec", "-T", "agent", "python", "-c", ct.HOP_MCP, stdin=json.dumps(req), timeout=90
    )
    if p.returncode != 0:
        return {"transport_error": True, "stderr": p.stderr.strip()[-200:]}
    return json.loads(p.stdout.strip().splitlines()[-1])  # type: ignore[no-any-return]


def mcp_token(kc: ct.Keycloak, login: str, audience: str, scope: str) -> str:
    """Như agent: đổi token đăng nhập -> token agent -> token đích (client agent-service)."""
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    return kc.token_for(agent_tok, audience, scope, client="agent-service")


def err_of(r: dict[str, Any]) -> tuple[str | None, str | None]:
    """(code, details.reason) của kết quả lỗi."""
    d = r.get("data") or {}
    if not isinstance(d, dict):
        return None, None
    det = d.get("details") if isinstance(d.get("details"), dict) else {}
    return d.get("code"), (det or {}).get("reason")


def refused(r: dict[str, Any]) -> bool:
    return r.get("is_error") is True or bool(r.get("transport_error"))


# ----------------------------------------------------------------------------- DB
def deliveries(intent_id: str | None = None) -> list[dict[str, Any]]:
    where = f" where intent_id = '{ct.lit(intent_id)}'" if intent_id else ""
    return ct.psql_json(
        "notify",
        f"select intent_id, channel, status, actor_sub, approval_jti, text_sha256 "
        f"from report_deliveries{where} order by id",
    )


# ----------------------------------------------------------------------------- mock LLM
def mock_script(channel: str, text: str) -> None:
    rules = [
        {
            "match": ct.ROUTER_MARK,
            "times": 1,
            "text": json.dumps({"route": "report", "confidence": 0.95, "reason": "e2e"}),
        },
        {
            "needs_tool": "prepare_send_group_report",
            "tool": "prepare_send_group_report",
            "times": 1,
            "args": {"channel": channel, "text": text},
        },
    ]
    r = ct.hop(
        "PUT",
        f"{MOCK}/__control/script",
        token=ct.secret("gw_admin_token"),
        body={"rules": rules},
    )
    if r.status != 200:
        raise RuntimeError(f"mock script rejected: {r.status}")


# ----------------------------------------------------------------------------- kịch bản
def scenario_positive(kc: ct.Keycloak) -> dict[str, Any]:
    R.section(f"A. Dương tính: {U_SEND} gửi báo cáo vào {CH_ENG} qua luồng phê duyệt đầy đủ")
    sub = kc.user_ids[U_SEND]
    login = kc.login(U_SEND)
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    text = f"E2E bao cao tuan {uuid.uuid4().hex[:8]}: phong ky thuat hoan thanh dung tien do"
    t = ct.hop("POST", f"{AGENT}/v1/threads", token=agent_tok, body={"title": "e2e notify"})
    thread_id = t.json()["thread_id"]
    mock_script(CH_ENG, text)
    run = ct.hop(
        "POST",
        f"{AGENT}/v1/threads/{thread_id}/runs",
        token=agent_tok,
        body={
            "input": {"text": f"gửi báo cáo tuần vào nhóm phòng Kỹ thuật: {text}"},
            "client_msg_id": "m" + uuid.uuid4().hex[:16],
        },
    )
    ev = ct.parse_sse(run.body) if run.status == 200 else []
    it = next((d for e, d in ev if e == "interrupt"), None)
    route = next((d for e, d in ev if e == "route"), {})
    R.check(
        "A1 agent: route=report, prepare_send_group_report ra interrupt (status=interrupted)",
        run.status == 200
        and route.get("route") == "report"
        and it is not None
        and next((d for e, d in ev if e == "done"), {}).get("status") == "interrupted",
        f"status={run.status} events={[e for e, _ in ev if e != 'token']}",
    )
    if it is None:
        raise RuntimeError("không có interrupt, dừng ca A")
    pl = it["payload"]
    intent_id, jws = pl["intent_id"], pl["intent_jws"]
    R.check(
        "A2 chưa gửi gì sau prepare (report_deliveries chưa có dòng cho intent)",
        deliveries(intent_id) == [],
    )

    signer_tok = kc.token_for(login, "approval-signer", "signer:approve")
    v = ct.signer_verify(signer_tok, jws)
    card = v.json() if v.status == 200 else {}
    flat = json.dumps(card, ensure_ascii=False)
    R.check(
        "A3 thẻ duyệt: op=send_group_report, hiện đủ kênh và nguyên văn nội dung",
        v.status == 200
        and card.get("op") == "send_group_report"
        and card.get("intent_id") == intent_id
        and CH_ENG in flat
        and text in flat,
        f"status={v.status}",
    )
    ap = ct.signer_approve(signer_tok, jws)
    approval_token = (ap.json() or {}).get("approval_token") if ap.status == 200 else None
    R.check(
        "A4 signer approve bằng token của chính user -> 200 + approval_token", bool(approval_token)
    )
    if not approval_token:
        raise RuntimeError("không có approval_token, dừng ca A")

    prep = ct.Prepared("", text, thread_id, it["interrupt_id"], intent_id, jws, ev, agent_tok)
    agent_tok2 = kc.token_for(login, "agent-service", "agent:invoke")
    rs = ct.resume(agent_tok2, prep, {"type": "approve", "approval_token": approval_token})
    rev = ct.parse_sse(rs.body) if rs.status == 200 else []
    R.check(
        "A5 resume: commit_intent ok, done.status=completed",
        rs.status == 200
        and any(e == "tool_end" and d.get("ok") for e, d in rev)
        and next((d for e, d in rev if e == "done"), {}).get("status") == "completed",
        f"status={rs.status} events={[e for e, _ in rev if e != 'token']}",
    )
    rows = deliveries(intent_id)
    R.check(
        "A6 DB report_deliveries: đúng 1 dòng, status=sent, kênh=dept-eng, actor=user",
        len(rows) == 1
        and rows[0]["status"] == "sent"
        and rows[0]["channel"] == CH_ENG
        and rows[0]["actor_sub"] == sub,
        str([(r["status"], r["channel"]) for r in rows]),
    )
    return {
        "login": login,
        "intent_id": intent_id,
        "approval_token": approval_token,
        "agent_tok": agent_tok2,
        "prep": prep,
        "sub": sub,
    }


def scenario_replay(kc: ct.Keycloak, a: dict[str, Any]) -> None:
    R.section("B. Replay: commit lại cùng approval/intent")
    intent_id = a["intent_id"]
    n_before = len(deliveries())
    rs2 = ct.resume(
        a["agent_tok"], a["prep"], {"type": "approve", "approval_token": a["approval_token"]}
    )
    R.check(
        "B1 resume lần 2 cùng interrupt (qua agent) bị từ chối (409)",
        rs2.status == 409,
        f"status={rs2.status} code={rs2.error_code()}",
    )
    tk = mcp_token(kc, a["login"], "notify-mcp", "notify:write")
    rp = mcp(
        NOTIFY_MCP,
        tk,
        "commit_intent",
        {"intent_id": intent_id, "approval_token": a["approval_token"]},
        a["prep"].thread_id,
    )
    code, _ = err_of(rp)
    R.check(
        "B2 commit_intent lại với CÙNG approval_token (gọi thẳng MCP) -> từ chối approval_replayed",
        rp.get("is_error") is True and code == "approval_replayed",
        f"code={code} transport={rp.get('transport_error')}",
    )
    rows = deliveries(intent_id)
    R.check(
        "B3 vẫn đúng 1 dòng sent cho intent, tổng số dòng không đổi",
        len(rows) == 1 and rows[0]["status"] == "sent" and len(deliveries()) == n_before,
    )


def scenario_arbitrary_channel(kc: ct.Keycloak) -> None:
    R.section("C. Chat ID / kênh tuỳ ý ngoài channels.yaml bị từ chối")
    n_before = len(deliveries())
    tk = mcp_token(kc, kc.login(U_SEND), "notify-mcp", "notify:write")
    for label, chan in (
        ("chat ID số âm -100123456", "-100123456"),
        ("username @foo", "@foo"),
        ("bí danh hợp lệ nhưng không khai (dept-foo)", "dept-foo"),
    ):
        r = mcp(NOTIFY_MCP, tk, "prepare_send_group_report", {"channel": chan, "text": "x e2e"})
        code, _ = err_of(r)
        R.check(
            f"C {label} -> từ chối, không tạo intent",
            refused(r) and not (r.get("data") or {}).get("intent_id"),
            f"code={code}",
        )
    # tham số lạ (chat_id) đi kèm bí danh hợp lệ cũng bị schema chặn
    r = mcp(
        NOTIFY_MCP,
        tk,
        "prepare_send_group_report",
        {"channel": CH_ENG, "text": "x e2e", "chat_id": "-100123456"},
    )
    R.check("C4 tham số thừa `chat_id` bị schema từ chối", refused(r), f"code={err_of(r)[0]}")
    R.check("C5 không có dòng report_deliveries mới", len(deliveries()) == n_before)


def scenario_other_dept(kc: ct.Keycloak) -> None:
    R.section(f"D. Kênh phòng khác: {U_SEND} (ENG) gửi {CH_SALES}")
    n_before = len(deliveries())
    tk = mcp_token(kc, kc.login(U_SEND), "notify-mcp", "notify:write")
    r = mcp(NOTIFY_MCP, tk, "prepare_send_group_report", {"channel": CH_SALES, "text": "x e2e"})
    code, _ = err_of(r)
    R.check("D1 prepare dept-sales bởi user ENG -> forbidden", code == "forbidden", f"code={code}")
    r = mcp(NOTIFY_MCP, tk, "prepare_send_group_report", {"channel": CH_ALL, "text": "x e2e"})
    code, _ = err_of(r)
    R.check(
        "D2 prepare company-all bởi team_lead (không có REPORT_COMPANY) -> forbidden",
        code == "forbidden",
        f"code={code}",
    )
    lst = mcp(NOTIFY_MCP, tk, "list_report_channels", {})
    names = sorted(c["channel"] for c in (lst.get("data") or {}).get("channels", []))
    R.check("D3 list_report_channels chỉ trả dept-eng", names == [CH_ENG], str(names))
    R.check("D4 không có dòng report_deliveries mới", len(deliveries()) == n_before)


def taint_thread(kc: ct.Keycloak, user: str, query: str) -> tuple[str, str, int]:
    """Đọc tài liệu qua docs-mcp trong một thread mới (docs-mcp ghi taint). Trả (login, thread, max_class)."""
    login = kc.login(user)
    thread_id = str(uuid.uuid4())
    dk = mcp_token(kc, login, "docs-mcp", "docs:read")
    res = mcp(DOCS_MCP, dk, "search_documents", {"query": query, "top_k": 8}, thread_id)
    hits = ((res.get("data") or {}).get("results")) or []
    mx = max((int(h.get("classification", 0)) for h in hits), default=0)
    return login, thread_id, mx


def scenario_taint(kc: ct.Keycloak) -> None:
    R.section("E. Taint: thread đã đọc tài liệu mật hơn mức tối đa của kênh bị chặn")
    n_before = len(deliveries())
    # E1: tài liệu mức 2 (báo cáo doanh số quý 3) > dept-sales.max_class=1
    login, th, mx = taint_thread(kc, U_TAINT_DEPT, "Báo cáo doanh số quý 3 năm 2026")
    R.check("E0 docs-mcp trả tài liệu mức >= 2 cho thread (dựng taint)", mx >= 2, f"max_class={mx}")
    tk = mcp_token(kc, login, "notify-mcp", "notify:write")
    r = mcp(NOTIFY_MCP, tk, "prepare_send_group_report", {"channel": CH_SALES, "text": "x e2e"}, th)
    code, reason = err_of(r)
    R.check(
        "E1 dept-sales (max_class 1) với thread taint mức 2 -> forbidden/taint_exceeds_channel",
        code == "forbidden" and reason == "taint_exceeds_channel",
        f"code={code} reason={reason}",
    )
    # E2: tài liệu mức 1 (nội quy) > company-all.max_class=0
    login, th, mx = taint_thread(kc, U_TAINT_ALL, "Nội quy làm việc")
    R.check(
        "E2a docs-mcp trả tài liệu mức >= 1 cho thread (dựng taint)", mx >= 1, f"max_class={mx}"
    )
    tk = mcp_token(kc, login, "notify-mcp", "notify:write")
    r = mcp(NOTIFY_MCP, tk, "prepare_send_group_report", {"channel": CH_ALL, "text": "x e2e"}, th)
    code, reason = err_of(r)
    R.check(
        "E2 company-all (max_class 0) với thread taint mức 1 -> forbidden/taint_exceeds_channel",
        code == "forbidden" and reason == "taint_exceeds_channel",
        f"code={code} reason={reason}",
    )
    R.check("E3 không có dòng report_deliveries mới", len(deliveries()) == n_before)


def scenario_blocking(kc: ct.Keycloak) -> None:
    R.section("F. Vai trò chặn ghi (admin, auditor) không prepare được")
    n_before = len(deliveries())
    for user in (U_ADMIN, U_AUDITOR):
        tk = mcp_token(kc, kc.login(user), "notify-mcp", "notify:write")
        for chan in (CH_ENG, CH_ALL):
            r = mcp(NOTIFY_MCP, tk, "prepare_send_group_report", {"channel": chan, "text": "x e2e"})
            code, _ = err_of(r)
            R.check(
                f"F {user} prepare {chan} -> forbidden",
                code == "forbidden" and not (r.get("data") or {}).get("intent_id"),
                f"code={code}",
            )
        lst = mcp(NOTIFY_MCP, tk, "list_report_channels", {})
        R.check(
            f"F {user} list_report_channels rỗng",
            (lst.get("data") or {}).get("channels") == [],
            str(lst.get("data"))[:120],
        )
    R.check("F5 không có dòng report_deliveries mới", len(deliveries()) == n_before)


# ----------------------------------------------------------------------------- main
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--keep-client", action="store_true", help="giữ client e2e-test (debug)")
    args = ap.parse_args()
    host = urlparse(ct.KC).hostname or ""
    if host not in ct.DEV_KC_HOSTS and os.environ.get("E2E_ALLOW") != "1":
        print(
            f"Từ chối chạy: Keycloak host {host!r} không phải dev (đặt E2E_ALLOW=1 để ép)",
            file=sys.stderr,
        )
        return 2
    t0 = time.time()
    print(f"E2E notify  run_id={uuid.uuid4().hex[:8]}")
    kc = ct.Keycloak()
    try:
        created = kc.ensure_test_setup(USERS)
        print(
            f"keycloak: client e2e-test {'ĐÃ TẠO' if created else 'đã có'}; "
            "mật khẩu test đặt lại (chỉ trong bộ nhớ)"
        )
        state: dict[str, Any] = {}
        steps = (
            ("A", lambda: state.update(a=scenario_positive(kc))),
            ("B", lambda: scenario_replay(kc, state["a"])),
            ("C", lambda: scenario_arbitrary_channel(kc)),
            ("D", lambda: scenario_other_dept(kc)),
            ("E", lambda: scenario_taint(kc)),
            ("F", lambda: scenario_blocking(kc)),
        )
        for label, fn in steps:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - ghi lỗi kịch bản rồi chạy tiếp
                R.check(
                    f"{label}-scenario hoàn tất không lỗi",
                    False,
                    f"{type(exc).__name__}: {str(exc)[:300]}",
                )
        with contextlib.suppress(Exception):
            ct.hop("DELETE", f"{MOCK}/__control", token=ct.secret("gw_admin_token"))
    finally:
        if args.keep_client:
            print(f"keycloak: GIỮ client {ct.E2E_CLIENT_ID} (--keep-client)")
        else:
            try:
                gone = kc.delete_client()
                print(f"keycloak: client {ct.E2E_CLIENT_ID} {'ĐÃ XOÁ' if gone else 'không còn'}")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  WARN: không xoá được client {ct.E2E_CLIENT_ID}: {type(exc).__name__}",
                    file=sys.stderr,
                )
    total = len(R.rows)
    print(f"\n{total - R.failed}/{total} assertion PASS, {R.failed} FAIL, {time.time() - t0:.0f}s")
    return 1 if R.failed else 0


if __name__ == "__main__":
    sys.exit(main())
