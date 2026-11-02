#!/usr/bin/env python3
"""Kiểm tra rò rỉ tài liệu trái quyền (ROADMAP R3) trên stack compose THẬT, 16 user mẫu.

Với mỗi user, "tài liệu trái quyền" được tính ĐỘC LẬP với RLS: từ thuộc tính user trong
`infra/keycloak/realm-acme.json` (department, clearance, vai trò) và bảng `documents` trong DB `knowledge`,
theo quy tắc ở contracts §5 (phòng của user hoặc ALL; classification <= clearance; allowed_roles rỗng hoặc
giao với vai trò). Dấu vết (canary) của mỗi tài liệu: doc_id, tiêu đề, và một "vân tay" 50-80 ký tự lấy từ
chunk đầu, duy nhất trong toàn bộ chunk (seed chưa có chuỗi canary riêng).

Bốn nơi được quét, rò rỉ nếu có bất kỳ dấu vết nào của tài liệu trái quyền:
  1. search_documents gọi THẲNG docs-mcp bằng token user thật (đổi qua Keycloak như agent): tiêu đề mọi tài
     liệu làm truy vấn + câu hỏi chủ đề + `department_filter` ép sang phòng lạ (phải chỉ thu hẹp, không mở rộng).
  2. SSE của agent (route docs, mock-provider được ép gọi search_documents với tiêu đề tài liệu trái quyền):
     mọi sự kiện, gồm tool_end, citations, token.
  3. Danh sách trích dẫn (sự kiện `citations` và trường `citations` trong lịch sử).
  4. Lịch sử thread: GET /v1/threads/{id}/messages sau mỗi lượt, và GET /v1/threads của user.
Đối chứng dương tính: mỗi user phải nhìn thấy ít nhất một tài liệu được phép (tránh trường hợp "0 rò rỉ" chỉ
vì không trả gì).

Đi thẳng agent (cùng đường BFF chuyển tiếp bằng token đã đổi), không qua cookie BFF: BFF không lọc/biến đổi
nội dung nên quyền nằm ở docs-mcp/RLS, đúng chỗ cần kiểm. Client Keycloak `e2e-test` dev-only, tạo rồi xoá
trong `finally`; mật khẩu ngẫu nhiên chỉ ở bộ nhớ.

Chạy: `bash scripts/e2e-leak-check.sh [--users a,b] [--agent-q 4]`. Báo cáo: eval/results/leak-check-<ts>.json.
Tác dụng phụ (dev): đặt lại mật khẩu các user được kiểm, ghi taint vào Redis và dòng tool_audit của docs-mcp.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import close_ticket as ct  # noqa: E402

AGENT, MOCK, ROOT = ct.AGENT, ct.MOCK, ct.ROOT
DOCS_MCP = "http://docs-mcp:8101/mcp"
REALM_JSON = ROOT / "infra" / "keycloak" / "realm-acme.json"

# Chạy nhiều lời gọi search_documents trong MỘT phiên MCP (một lần docker exec cho cả batch).
HOP_MCP_BATCH = r"""
import sys, json, asyncio, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
r = json.load(sys.stdin)
async def main():
    out = []
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + r["token"]}, timeout=60) as hc:
        async with Client(streamable_http_client(r["url"], http_client=hc)) as c:
            for call in r["calls"]:
                try:
                    res = await c.call_tool(call["tool"], call["args"],
                                            meta={"io.acme/thread_id": call["thread_id"]})
                    data = res.structured_content
                    if data is None:
                        text = "".join(getattr(b, "text", "") for b in res.content)
                        try:
                            data = json.loads(text)
                        except ValueError:
                            data = {"text": text}
                    out.append({"is_error": bool(res.is_error), "data": data})
                except Exception as exc:
                    out.append({"transport_error": type(exc).__name__})
    print(json.dumps(out))
asyncio.run(main())
"""

GENERIC_QUERIES = [
    "bảng lương nhân viên",
    "kỷ luật nhân viên vi phạm",
    "chiến lược định giá và chiết khấu",
    "danh sách khách hàng chiến lược",
    "kế hoạch điều chỉnh lương năm 2027",
    "doanh số quý 3",
    "thưởng KPI năm 2026",
    "kế hoạch kinh doanh mở rộng thị trường",
]
ALL_DEPTS = ["SALES", "ENG", "HR", "CS", "IT"]


@dataclass
class Doc:
    id: str
    title: str
    department: str
    classification: int
    allowed_roles: list[str]
    fingerprint: str


@dataclass
class UserCase:
    name: str
    depts: set[str]
    clearance: int
    roles: set[str]
    allowed: list[Doc] = field(default_factory=list)
    forbidden: list[Doc] = field(default_factory=list)


def load_users(only: set[str] | None) -> list[UserCase]:
    realm = json.loads(REALM_JSON.read_text(encoding="utf-8"))
    out = []
    for u in realm["users"]:
        if only and u["username"] not in only:
            continue
        a = u["attributes"]
        out.append(
            UserCase(
                u["username"],
                set(a["department"]),
                int(a["clearance"][0]),
                set(u.get("realmRoles", [])),
            )
        )
    return out


def load_docs() -> list[Doc]:
    rows = ct.psql_json(
        "knowledge",
        r"""
        select d.id, d.title, d.department, d.classification, d.allowed_roles,
               (select substring(c.content from '[^\n]{40,80}')
                  from chunks c
                 where c.document_id = d.id and c.content ~ '[^\n]{40,80}'
                 order by c.ord limit 1) as fp
        from documents d
        order by d.id
        """,
    )
    docs = []
    for r in rows:
        fp = r["fp"] or ""
        docs.append(
            Doc(r["id"], r["title"], r["department"], r["classification"], r["allowed_roles"], fp)
        )
    # vân tay phải duy nhất trong toàn bộ chunk, nếu không sẽ báo động giả
    for d in docs:
        if not d.fingerprint:
            continue
        n = ct.psql_json(
            "knowledge",
            "select count(distinct document_id) as n from chunks where position("
            f"{_sql_str(d.fingerprint)} in content) > 0",
        )[0]["n"]
        if n != 1:
            d.fingerprint = ""  # bỏ vân tay mơ hồ; vẫn còn doc_id + tiêu đề
    return docs


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def visible(u: UserCase, d: Doc) -> bool:
    """Quy tắc contracts §5, viết lại độc lập với RLS."""
    return (
        (d.department == "ALL" or d.department in u.depts)
        and d.classification <= u.clearance
        and (not d.allowed_roles or bool(set(d.allowed_roles) & u.roles))
    )


# ----------------------------------------------------------------------------- phát hiện
def scan_blob(blob: str, forbidden: list[Doc], *, strip: list[str] = ()) -> dict[str, set[str]]:
    """Trả {"hard": {doc_id...}, "title": {doc_id...}}. hard = doc_id hoặc vân tay; title = chỉ tiêu đề."""
    for s in strip:
        blob = blob.replace(s, "")
    hard: set[str] = set()
    title: set[str] = set()
    for d in forbidden:
        if d.id in blob or (d.fingerprint and d.fingerprint in blob):
            hard.add(d.id)
        elif d.title in blob:
            title.add(d.id)
    return {"hard": hard, "title": title}


def flat(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


@dataclass
class Tally:
    queries: int = 0
    hits: int = 0
    ctrl_hits: int = 0
    hard: set[str] = field(default_factory=set)
    title: set[str] = field(default_factory=set)
    where: list[str] = field(default_factory=list)

    def add(self, found: dict[str, set[str]], where: str) -> None:
        if found["hard"] or found["title"]:
            self.where.append(
                f"{where}: hard={sorted(found['hard'])} title={sorted(found['title'])}"
            )
        self.hard |= found["hard"]
        self.title |= found["title"]


# ----------------------------------------------------------------------------- 1. docs-mcp trực tiếp
def check_direct(kc: ct.Keycloak, u: UserCase) -> Tally:
    t = Tally()
    login = kc.login(u.name)
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    tok = kc.token_for(agent_tok, "docs-mcp", "docs:read", client="agent-service")
    queries: list[tuple[str, dict[str, Any]]] = []
    for d in u.forbidden + u.allowed:
        queries.append((d.title, {"query": d.title, "top_k": 10}))
    for q in GENERIC_QUERIES:
        queries.append((q, {"query": q, "top_k": 10}))
    for dept in ALL_DEPTS:
        if dept not in u.depts:  # ép sang phòng lạ: chỉ được thu hẹp, không mở rộng quyền
            queries.append(
                (
                    f"filter={dept}",
                    {"query": "chính sách quy trình", "top_k": 10, "department_filter": dept},
                )
            )
    calls = [
        {"tool": "search_documents", "args": a, "thread_id": str(uuid.uuid4())} for _, a in queries
    ]
    p = ct.compose(
        "exec",
        "-T",
        "agent",
        "python",
        "-c",
        HOP_MCP_BATCH,
        stdin=json.dumps({"token": tok, "url": DOCS_MCP, "calls": calls}),
        timeout=600,
    )
    if p.returncode != 0:
        raise RuntimeError(f"batch MCP lỗi: {p.stderr.strip()[-200:]}")
    results = json.loads(p.stdout.strip().splitlines()[-1])
    allowed_ids = {d.id for d in u.allowed}
    for (label, _), res in zip(queries, results, strict=True):
        t.queries += 1
        if res.get("transport_error"):
            t.add({"hard": set(), "title": set()}, f"{label}: transport_error")
            t.where.append(f"{label}: transport_error={res['transport_error']}")
            continue
        items = (res.get("data") or {}).get("results") or []
        t.hits += len(items)
        t.ctrl_hits += sum(1 for it in items if it.get("doc_id") in allowed_ids)
        # quét CẢ kết quả có cấu trúc lẫn toàn bộ payload (text, content, heading...)
        t.add(scan_blob(flat(res.get("data")), u.forbidden, strip=[label]), f"search[{label}]")
        for it in items:
            if it.get("doc_id") not in allowed_ids:
                t.add(
                    {"hard": {it.get("doc_id", "?")}, "title": set()}, f"search[{label}] doc_id lạ"
                )
    return t


# ----------------------------------------------------------------------------- 2-4. qua agent
def mock_script(query: str) -> None:
    rules = [
        {
            "match": ct.ROUTER_MARK,
            "times": 1,
            "text": json.dumps({"route": "docs", "confidence": 0.95, "reason": "leak-check"}),
        },
        {
            "needs_tool": "search_documents",
            "tool": "search_documents",
            "times": 1,
            "args": {"query": query, "top_k": 8},
        },
    ]
    r = ct.hop(
        "PUT", f"{MOCK}/__control/script", token=ct.secret("gw_admin_token"), body={"rules": rules}
    )
    if r.status != 200:
        raise RuntimeError(f"mock script rejected: {r.status}")


def pick(u: UserCase, n: int, offset: int) -> list[Doc]:
    ordered = sorted(u.forbidden, key=lambda d: (-d.classification, d.id))
    if not ordered:
        return []
    return [ordered[(offset + i) % len(ordered)] for i in range(min(n, len(ordered)))]


def check_agent(kc: ct.Keycloak, u: UserCase, n: int, offset: int) -> Tally:
    t = Tally()
    login = kc.login(u.name)
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    questions = [
        (d.title, f"Cho tôi biết nội dung tài liệu: {d.title}") for d in pick(u, n, offset)
    ]
    if u.allowed:  # đối chứng dương tính
        d0 = sorted(u.allowed, key=lambda d: d.id)[0]
        questions.append((d0.title, f"Tóm tắt tài liệu: {d0.title}"))
    allowed_ids = {d.id for d in u.allowed}
    threads: list[str] = []
    for query, text in questions:
        th = ct.hop("POST", f"{AGENT}/v1/threads", token=agent_tok, body={"title": "leak-check"})
        if th.status != 201:
            t.where.append(f"create_thread -> {th.status}")
            continue
        tid = th.json()["thread_id"]
        threads.append(tid)
        mock_script(query)
        run = ct.hop(
            "POST",
            f"{AGENT}/v1/threads/{tid}/runs",
            token=agent_tok,
            body={"input": {"text": text}, "client_msg_id": "m" + uuid.uuid4().hex[:16]},
        )
        t.queries += 1
        if run.status != 200:
            t.where.append(f"run[{query}] -> {run.status}")
            continue
        ev = ct.parse_sse(run.body)
        # citations: mọi item phải thuộc tài liệu được phép
        for e, d in ev:
            if e == "citations":
                for it in d.get("items") or []:
                    t.hits += 1
                    if it.get("doc_id") in allowed_ids:
                        t.ctrl_hits += 1
                    elif it.get("doc_id"):
                        t.add(
                            {"hard": {it["doc_id"]}, "title": set()},
                            f"citations[{query}] doc_id lạ",
                        )
        t.add(scan_blob(flat(ev), u.forbidden, strip=[query, text]), f"sse[{query}]")
        msgs = ct.hop("GET", f"{AGENT}/v1/threads/{tid}/messages", token=agent_tok)
        t.add(scan_blob(msgs.body, u.forbidden, strip=[query, text]), f"history[{query}]")
        # msgs.body là JSON thoát unicode? thử cả dạng đã parse
        if msgs.status == 200:
            t.add(
                scan_blob(flat(msgs.json()), u.forbidden, strip=[query, text]),
                f"history-parsed[{query}]",
            )
            for m in msgs.json().get("messages", []):
                for it in m.get("citations") or []:
                    if it.get("doc_id") not in allowed_ids:
                        t.add(
                            {"hard": {str(it.get("doc_id"))}, "title": set()},
                            f"history.citations[{query}] doc_id lạ",
                        )
        else:
            t.where.append(f"history[{query}] -> {msgs.status}")
    lst = ct.hop("GET", f"{AGENT}/v1/threads?limit=100", token=agent_tok)
    if lst.status == 200:
        t.add(
            scan_blob(flat(lst.json()), u.forbidden, strip=[q for q, _ in questions]), "thread-list"
        )
    for tid in threads:  # dọn thread của lượt kiểm tra
        with contextlib.suppress(Exception):
            ct.hop("DELETE", f"{AGENT}/v1/threads/{tid}", token=agent_tok)
    return t


# ----------------------------------------------------------------------------- main
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--users", default="", help="danh sách user, phẩy ngăn cách (mặc định cả 16)")
    ap.add_argument(
        "--agent-q", type=int, default=4, help="số câu tài liệu trái quyền/user qua agent"
    )
    ap.add_argument("--keep-client", action="store_true", help="giữ client e2e-test (debug)")
    args = ap.parse_args()
    host = urlparse(ct.KC).hostname or ""
    if host not in ct.DEV_KC_HOSTS and os.environ.get("E2E_ALLOW") != "1":
        print(f"Từ chối chạy: Keycloak host {host!r} không phải dev", file=sys.stderr)
        return 2
    t0 = time.time()
    only = {x for x in args.users.split(",") if x} or None
    users = load_users(only)
    docs = load_docs()
    for u in users:
        u.allowed = [d for d in docs if visible(u, d)]
        u.forbidden = [d for d in docs if not visible(u, d)]
    print(
        f"Leak-check: {len(users)} user, {len(docs)} tài liệu, canary = doc_id + tiêu đề + vân tay"
    )
    kc = ct.Keycloak()
    rows: list[dict[str, Any]] = []
    try:
        created = kc.ensure_test_setup([u.name for u in users])
        print(
            f"keycloak: client e2e-test {'ĐÃ TẠO' if created else 'đã có'}; mật khẩu test đặt lại"
        )
        for i, u in enumerate(users):
            row: dict[str, Any] = {
                "user": u.name,
                "depts": sorted(u.depts),
                "clearance": u.clearance,
                "roles": sorted(u.roles),
                "n_allowed": len(u.allowed),
                "n_forbidden": len(u.forbidden),
            }
            for label, fn in (
                ("direct", lambda u=u: check_direct(kc, u)),
                ("agent", lambda u=u, i=i: check_agent(kc, u, args.agent_q, i * 3)),
            ):
                try:
                    t = fn()
                    row[label] = {
                        "queries": t.queries,
                        "hits": t.hits,
                        "control_hits": t.ctrl_hits,
                        "leaks_hard": sorted(t.hard),
                        "leaks_title_only": sorted(t.title),
                        "where": t.where[:20],
                    }
                except Exception as exc:  # noqa: BLE001 - ghi lỗi rồi chạy tiếp
                    row[label] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            rows.append(row)
            print(_line(row), flush=True)
    finally:
        with contextlib.suppress(Exception):
            ct.mock_reset()
        if args.keep_client:
            print(f"keycloak: GIỮ client {ct.E2E_CLIENT_ID} (--keep-client)")
        else:
            try:
                gone = kc.delete_client()
                print(f"keycloak: client {ct.E2E_CLIENT_ID} {'ĐÃ XOÁ' if gone else 'không còn'}")
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN: không xoá được client: {type(exc).__name__}", file=sys.stderr)

    def total(key: str, sub: str) -> int:
        return sum(len(r.get(sub, {}).get(key, [])) for r in rows)

    hard = total("leaks_hard", "direct") + total("leaks_hard", "agent")
    soft = total("leaks_title_only", "direct") + total("leaks_title_only", "agent")
    errors = sum(1 for r in rows for s in ("direct", "agent") if "error" in r.get(s, {}))
    vacuous = [r["user"] for r in rows if r["direct"].get("control_hits", 0) == 0]
    summary = {
        "users": len(rows),
        "leaks_hard": hard,
        "leaks_title_only": soft,
        "errors": errors,
        "users_without_positive_control": vacuous,
        "seconds": round(time.time() - t0),
    }
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"leak-check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("\n" + _table(rows))
    print(f"\nTổng kết: {summary}\nBáo cáo: {out.relative_to(ROOT)}")
    return 1 if (hard or soft or errors or vacuous) else 0


def _cell(r: dict[str, Any], key: str) -> tuple[str, str, str, str]:
    s = r.get(key, {})
    if "error" in s:
        return ("ERR", "-", "-", "-")
    return (
        str(s["queries"]),
        str(s["control_hits"]),
        str(len(s["leaks_hard"])),
        str(len(s["leaks_title_only"])),
    )


def _line(r: dict[str, Any]) -> str:
    d, a = _cell(r, "direct"), _cell(r, "agent")
    return (
        f"  {r['user']:<11} direct q={d[0]} leak={d[2]}/{d[3]}  agent q={a[0]} leak={a[2]}/{a[3]}"
    )


def _table(rows: list[dict[str, Any]]) -> str:
    head = (
        f"{'user':<11} {'phòng':<18} {'cl':>2} {'cấm':>4} | "
        f"{'MCP q':>5} {'đối chứng':>9} {'rò':>3} {'rò-tiêu-đề':>10} | "
        f"{'agent q':>7} {'đối chứng':>9} {'rò':>3} {'rò-tiêu-đề':>10}"
    )
    lines = [head, "-" * len(head)]
    for r in rows:
        d, a = _cell(r, "direct"), _cell(r, "agent")
        lines.append(
            f"{r['user']:<11} {','.join(r['depts']):<18} {r['clearance']:>2} {r['n_forbidden']:>4} | "
            f"{d[0]:>5} {d[1]:>9} {d[2]:>3} {d[3]:>10} | {a[0]:>7} {a[1]:>9} {a[2]:>3} {a[3]:>10}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
