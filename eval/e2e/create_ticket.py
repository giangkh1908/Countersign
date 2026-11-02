#!/usr/bin/env python3
"""E2E tạo ticket (prepare_create_ticket -> thẻ duyệt -> signer -> resume -> commit) trên stack THẬT.

Cần: stack chạy profile `tickets`. Dùng lại hạ tầng của `close_ticket.py` (client Keycloak dev-only
`e2e-test` tạo qua Admin API và xoá ở cuối trong `finally`, mật khẩu ngẫu nhiên chỉ ở bộ nhớ, hop vào
container, LLM là mock-provider được ép kịch bản).

Hai đường đi:
  * Qua agent như BFF (đăng nhập -> exchange -> agent /threads, /runs, /resume + approval-signer):
    ca dương tính (cùng phòng và phòng khác), từ chối duyệt, replay qua agent.
  * Gọi THẲNG tickets-mcp từ container `agent` bằng token user thật đổi qua Keycloak: replay approval,
    vai trò chặn ghi (admin/auditor) và mức mật vượt clearance (mock không ép được tham số xấu tới đó;
    đi thẳng MCP là đường kiểm đúng chỗ phân quyền).

Chạy: `bash scripts/e2e-create-ticket.sh`. Tác dụng phụ (dev): đặt lại mật khẩu 5 user test và THÊM 2
ticket thật vào DB tickets (tiêu đề có nhãn E2ECT-<run_id>); ticket không bị xoá.
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
AGENT, MOCK = ct.AGENT, ct.MOCK

U_OK = "an.nguyen"  # SALES, employee, clearance 1
U_CLR0 = "tam.vu"  # SALES, employee, clearance 0
U_ADMIN = "oanh.ly"  # employee + admin (WRITE_BLOCKING)
U_AUDITOR = "quynh.dinh"  # auditor (WRITE_BLOCKING)
U_MGMT = "phuc.cao"  # management (nhiều phòng)
USERS = [U_OK, U_CLR0, U_ADMIN, U_AUDITOR, U_MGMT]


def tickets_by_tag(tag: str) -> list[dict[str, Any]]:
    return ct.psql_json(
        "tickets",
        "select t.code, t.title, t.status, t.requester_sub, t.requester_dept, t.assignee_dept, "
        "t.classification, t.category, "
        "(select count(*) from ticket_events e where e.ticket_id = t.id and e.action = 'create') "
        "as n_create "
        f"from tickets t where t.title like '%{ct.lit(tag)}%' order by t.id",
    )


def n_tickets() -> int:
    return int(ct.psql_json("tickets", "select count(*) as n from tickets")[0]["n"])


def n_events(intent_id: str) -> int:
    return len(
        ct.psql_json(
            "tickets", f"select id from ticket_events where intent_id = '{ct.lit(intent_id)}'"
        )
    )


def mcp_token(kc: ct.Keycloak, login: str) -> str:
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    return kc.token_for(agent_tok, "tickets-mcp", "tickets:write", client="agent-service")


def err_code(r: dict[str, Any]) -> str | None:
    d = r.get("data")
    return d.get("code") if isinstance(d, dict) else None


def refused(r: dict[str, Any]) -> bool:
    return r.get("is_error") is True or bool(r.get("transport_error"))


def mock_script(args: dict[str, Any]) -> None:
    rules = [
        {
            "match": ct.ROUTER_MARK,
            "times": 1,
            "text": json.dumps({"route": "ticket", "confidence": 0.95, "reason": "e2e"}),
        },
        {
            "needs_tool": "prepare_create_ticket",
            "tool": "prepare_create_ticket",
            "times": 1,
            "args": args,
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


def start_run(kc: ct.Keycloak, login: str, args: dict[str, Any]) -> tuple[str, str, ct.Resp]:
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    t = ct.hop("POST", f"{AGENT}/v1/threads", token=agent_tok, body={"title": "e2e create"})
    assert t.status == 201, f"create_thread -> {t.status}"
    thread_id = t.json()["thread_id"]
    mock_script(args)
    run = ct.hop(
        "POST",
        f"{AGENT}/v1/threads/{thread_id}/runs",
        token=agent_tok,
        body={
            "input": {"text": f"tạo ticket: {args['title']}"},
            "client_msg_id": "m" + uuid.uuid4().hex[:16],
        },
    )
    assert run.status == 200, f"run -> {run.status} {run.error_code()}"
    return agent_tok, thread_id, run


def prepare_via_agent(kc: ct.Keycloak, login: str, args: dict[str, Any]) -> tuple[ct.Prepared, str]:
    agent_tok, thread_id, run = start_run(kc, login, args)
    ev = ct.parse_sse(run.body)
    it = next((d for e, d in ev if e == "interrupt"), None)
    route = next((d for e, d in ev if e == "route"), {})
    assert it is not None, (
        f"không có interrupt; events={[e for e, _ in ev if e != 'token']} "
        f"err={[d for e, d in ev if e == 'error']}"
    )
    pl = it["payload"]
    prep = ct.Prepared(
        "",
        args["title"],
        thread_id,
        it["interrupt_id"],
        pl["intent_id"],
        pl["intent_jws"],
        ev,
        agent_tok,
    )
    return prep, route.get("route", "")


def scenario_positive(kc: ct.Keycloak, tag: str, dept: str, label: str) -> dict[str, Any]:
    R.section(f"{label}. Dương tính: {U_OK} (SALES) tạo ticket giao phòng {dept}, duyệt đầy đủ")
    sub = kc.user_ids[U_OK]
    login = kc.login(U_OK)
    title = f"E2ECT-{tag}-{label} giao {dept}"
    args = {
        "title": title,
        "body": "Noi dung kiem thu E2E tao ticket",
        "category": "complaint",
        "assignee_dept": dept,
        "priority": "low",
        "classification": 1,
    }
    n0 = n_tickets()
    prep, route = prepare_via_agent(kc, login, args)
    R.check(f"{label}1 route=ticket, prepare_create_ticket ra interrupt", route == "ticket")
    R.check(
        f"{label}2 chưa ghi gì sau prepare (số ticket không đổi, chưa có sự kiện)",
        n_tickets() == n0 and n_events(prep.intent_id) == 0,
        f"n0={n0} now={n_tickets()}",
    )
    signer_tok = kc.token_for(login, "approval-signer", "signer:approve")
    v = ct.signer_verify(signer_tok, prep.intent_jws)
    card = v.json() if v.status == 200 else {}
    flat = json.dumps(card, ensure_ascii=False)
    R.check(
        f"{label}3 thẻ duyệt: op=create_ticket, hiện tiêu đề và phòng {dept}",
        v.status == 200 and card.get("op") == "create_ticket" and title in flat and dept in flat,
        f"status={v.status}",
    )
    ap = ct.signer_approve(signer_tok, prep.intent_jws)
    token = (ap.json() or {}).get("approval_token") if ap.status == 200 else None
    R.check(f"{label}4 signer approve -> 200 + approval_token", bool(token))
    if not token:
        raise RuntimeError("không có approval_token")
    agent_tok2 = kc.token_for(login, "agent-service", "agent:invoke")
    rs = ct.resume(agent_tok2, prep, {"type": "approve", "approval_token": token})
    rev = ct.parse_sse(rs.body) if rs.status == 200 else []
    R.check(
        f"{label}5 resume: commit ok, done.status=completed",
        rs.status == 200
        and any(e == "tool_end" and d.get("ok") for e, d in rev)
        and next((d for e, d in rev if e == "done"), {}).get("status") == "completed",
        f"status={rs.status} events={[e for e, _ in rev if e != 'token']}",
    )
    rows = [r for r in tickets_by_tag(tag) if r["title"] == title]
    R.check(
        f"{label}6 DB: đúng 1 ticket mới (+1), requester=user, requester_dept=SALES, "
        f"assignee_dept={dept}, status=open, 1 sự kiện create",
        len(rows) == 1
        and n_tickets() == n0 + 1
        and rows[0]["requester_sub"] == sub
        and rows[0]["requester_dept"] == "SALES"
        and rows[0]["assignee_dept"] == dept
        and rows[0]["status"] == "open"
        and rows[0]["n_create"] == 1
        and n_events(prep.intent_id) == 1,
        str([(r["code"], r["requester_dept"], r["assignee_dept"]) for r in rows]),
    )
    return {"prep": prep, "token": token, "login": login, "agent_tok": agent_tok2}


def scenario_reject(kc: ct.Keycloak, tag: str) -> None:
    R.section(f"C. Từ chối duyệt: {U_OK} reject -> không ghi gì")
    login = kc.login(U_OK)
    args = {
        "title": f"E2ECT-{tag}-C tu choi",
        "body": "Noi dung kiem thu tu choi",
        "category": "complaint",
        "assignee_dept": "SALES",
    }
    n0 = n_tickets()
    prep, _ = prepare_via_agent(kc, login, args)
    rs = ct.resume(prep.agent_token, prep, {"type": "reject"})
    rev = ct.parse_sse(rs.body) if rs.status == 200 else []
    R.check(
        "C1 resume reject -> 200, không có tool_end ok (không commit)",
        rs.status == 200 and not any(e == "tool_end" and d.get("ok") for e, d in rev),
        f"status={rs.status} events={[e for e, _ in rev if e != 'token']}",
    )
    R.check(
        "C2 DB: không có ticket mới, không có sự kiện cho intent",
        n_tickets() == n0 and tickets_by_tag(tag + "-C") == [] and n_events(prep.intent_id) == 0,
        f"n0={n0} now={n_tickets()}",
    )
    # approve sau reject với token hợp lệ cũng không được ghi (interrupt đã đóng)
    signer_tok = kc.token_for(login, "approval-signer", "signer:approve")
    ap = ct.signer_approve(signer_tok, prep.intent_jws)
    tk = (ap.json() or {}).get("approval_token") if ap.status == 200 else None
    R.check("C3 signer vẫn cấp approval cho intent đã reject (để thử resume)", bool(tk))
    if tk:
        r2 = ct.resume(prep.agent_token, prep, {"type": "approve", "approval_token": tk})
        R.check(
            "C4 approve SAU reject (cùng interrupt) bị từ chối, vẫn không có ticket",
            ct.rejected(r2) and n_tickets() == n0 and n_events(prep.intent_id) == 0,
            f"status={r2.status}",
        )


def scenario_replay(kc: ct.Keycloak, a: dict[str, Any]) -> None:
    R.section("D. Replay: dùng lại approval/intent đã commit")
    prep = a["prep"]
    n0 = n_tickets()
    rs2 = ct.resume(a["agent_tok"], prep, {"type": "approve", "approval_token": a["token"]})
    R.check(
        "D1 resume lần 2 cùng interrupt (qua agent) bị từ chối",
        ct.rejected(rs2),
        f"status={rs2.status}",
    )
    tk = mcp_token(kc, a["login"])
    rp = ct.mcp_call(
        tk, "commit_intent", {"intent_id": prep.intent_id, "approval_token": a["token"]}
    )
    R.check(
        "D2 commit_intent lại cùng approval_token (thẳng MCP) -> từ chối",
        refused(rp),
        f"code={err_code(rp)}",
    )
    R.check(
        "D3 vẫn đúng 1 sự kiện create cho intent, tổng số ticket không đổi",
        n_events(prep.intent_id) == 1 and n_tickets() == n0,
        f"n0={n0} now={n_tickets()}",
    )


def scenario_blocking(kc: ct.Keycloak, tag: str) -> None:
    R.section("E. Vai trò chặn ghi (admin, auditor) không tạo được ticket")
    n0 = n_tickets()
    for user in (U_ADMIN, U_AUDITOR):
        tk = mcp_token(kc, kc.login(user))
        r = ct.mcp_call(
            tk,
            "prepare_create_ticket",
            {
                "title": f"E2ECT-{tag}-E {user}",
                "body": "khong duoc tao",
                "category": "complaint",
                "assignee_dept": "IT",
            },
        )
        R.check(
            f"E {user} prepare_create_ticket -> forbidden, không có intent",
            err_code(r) == "forbidden" and not (r.get("data") or {}).get("intent_id"),
            f"code={err_code(r)}",
        )
    # qua agent: dù LLM gọi prepare, không được có thẻ duyệt
    _, _, run = start_run(
        kc,
        kc.login(U_ADMIN),
        {
            "title": f"E2ECT-{tag}-E qua agent",
            "body": "khong duoc tao",
            "category": "complaint",
            "assignee_dept": "IT",
        },
    )
    ev = ct.parse_sse(run.body)
    R.check(
        "E3 admin qua agent: không có interrupt (không có thẻ duyệt)",
        not any(e == "interrupt" for e, _ in ev),
        f"events={[e for e, _ in ev if e != 'token']}",
    )
    R.check("E4 không có ticket mới", n_tickets() == n0 and tickets_by_tag(tag + "-E") == [])


def scenario_clearance(kc: ct.Keycloak, tag: str) -> None:
    R.section(f"F. Mức mật vượt clearance: {U_CLR0} (clearance 0)")
    n0 = n_tickets()
    tk = mcp_token(kc, kc.login(U_CLR0))
    base = {
        "title": f"E2ECT-{tag}-F clearance",
        "body": "kiem thu muc mat",
        "category": "complaint",
        "assignee_dept": "SALES",
    }
    r = ct.mcp_call(tk, "prepare_create_ticket", {**base, "classification": 3})
    R.check(
        "F1 classification=3 > clearance 0 -> forbidden",
        err_code(r) == "forbidden" and not (r.get("data") or {}).get("intent_id"),
        f"code={err_code(r)}",
    )
    r = ct.mcp_call(tk, "prepare_create_ticket", base)  # mặc định classification=1 > clearance 0
    R.check(
        "F2 mặc định classification=1 > clearance 0 -> forbidden",
        err_code(r) == "forbidden",
        f"code={err_code(r)}",
    )
    r = ct.mcp_call(tk, "prepare_create_ticket", {**base, "classification": 0})
    R.check(
        "F3 classification=0 (trong clearance) -> có intent, CHƯA ghi ticket",
        bool((r.get("data") or {}).get("intent_id")) and n_tickets() == n0,
        f"code={err_code(r)}",
    )
    r = ct.mcp_call(
        tk, "prepare_create_ticket", {**base, "assignee_dept": "hr; drop", "classification": 0}
    )
    R.check("F4 assignee_dept sai định dạng bị schema từ chối", refused(r))
    R.check("F5 không có ticket mới", n_tickets() == n0)


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
        print(f"Từ chối chạy: Keycloak host {host!r} không phải dev", file=sys.stderr)
        return 2
    t0 = time.time()
    tag = uuid.uuid4().hex[:8]
    print(f"E2E create-ticket  run_id={tag}")
    kc = ct.Keycloak()
    try:
        created = kc.ensure_test_setup(USERS)
        print(
            f"keycloak: client e2e-test {'ĐÃ TẠO' if created else 'đã có'}; "
            "mật khẩu test đặt lại (chỉ trong bộ nhớ)"
        )
        state: dict[str, Any] = {}
        steps = (
            ("A", lambda: state.update(a=scenario_positive(kc, tag, "SALES", "A"))),
            ("B", lambda: scenario_positive(kc, tag, "IT", "B")),
            ("C", lambda: scenario_reject(kc, tag)),
            ("D", lambda: scenario_replay(kc, state["a"])),
            ("E", lambda: scenario_blocking(kc, tag)),
            ("F", lambda: scenario_clearance(kc, tag)),
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
        ok, d = ct.verify_audit_chain("tickets")
        R.check("Z1 hash-chain tool_audit(tickets) vẫn verify OK", ok, d)
        R.check(
            "Z2 tổng cộng đúng 2 ticket mới của lượt chạy này (A và B)",
            len(tickets_by_tag(tag)) == 2,
            str([r["code"] for r in tickets_by_tag(tag)]),
        )
        with contextlib.suppress(Exception):
            ct.mock_reset()
    finally:
        if args.keep_client:
            print(f"keycloak: GIỮ client {ct.E2E_CLIENT_ID} (--keep-client)")
        else:
            try:
                gone = kc.delete_client()
                print(f"keycloak: client {ct.E2E_CLIENT_ID} {'ĐÃ XOÁ' if gone else 'không còn'}")
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN: không xoá được client: {type(exc).__name__}", file=sys.stderr)
    total = len(R.rows)
    print(f"\n{total - R.failed}/{total} assertion PASS, {R.failed} FAIL, {time.time() - t0:.0f}s")
    return 1 if R.failed else 0


if __name__ == "__main__":
    sys.exit(main())
