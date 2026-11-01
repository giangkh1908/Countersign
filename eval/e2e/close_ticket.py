#!/usr/bin/env python3
"""E2E "đóng ticket" trên stack compose THẬT, không trình duyệt.

Luồng (lặp lại đúng các lời gọi của BFF): token người dùng (Keycloak, client dev-only `e2e-test`)
-> exchange `aud=agent-service` / `aud=approval-signer` bằng client `chat-ui` (như BFF) -> agent
`/v1/threads`, `/runs` (SSE) tới interrupt -> approval-signer `/v1/intents/verify` + `/v1/approvals`
-> agent `/resume` -> tickets-mcp ghi DB. Mọi assertion đọc trạng thái thật (Postgres, hash-chain audit).

LLM là mock-provider; định tuyến được ép bằng kịch bản `PUT /__control/script` (xem mock_provider).
Các service nội bộ không publish cổng ra host nên HTTP nội bộ đi qua `docker compose exec bff|agent`
(hop); không in token/secret. Chạy: `bash scripts/e2e-close-ticket.sh [--skip-expiry]`.

Tác dụng phụ trên stack (dev): script SỞ HỮU vòng đời client `e2e-test` (tạo qua Admin API nếu thiếu,
xoá ở cuối trong `finally`; `--keep-client` để giữ khi debug; client KHÔNG nằm trong realm-acme.json),
đặt mật khẩu ngẫu nhiên cho 2 user test (chỉ giữ trong bộ nhớ), đóng 1 ticket seed mỗi lần chạy.
Từ chối chạy nếu Keycloak không phải dev (localhost / keycloak.acme.local) trừ khi `E2E_ALLOW=1`.
Hãy backup trước (pg_dumpall).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets as pysecrets
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from acme_common.adapters.audit_pg import select_sql
from acme_common.services.audit_chain import AuditKeyring, verify_chain

ROOT = Path(__file__).resolve().parents[2]
KC = "http://localhost:8080"  # issuer cố định bởi KC_HOSTNAME nên gọi qua localhost vẫn đúng `iss`
REALM = "acme"
AGENT = "http://agent:8200"
SIGNER = "http://approval-signer:8310"
MOCK = "http://mock-provider:8900"
TICKETS_MCP = "http://tickets-mcp:8102/mcp"
E2E_CLIENT_ID = "e2e-test"
DEV_KC_HOSTS = frozenset({"localhost", "127.0.0.1", "keycloak.acme.local"})
# Client dev-only, public + direct grant: KHÔNG được nằm trong realm-acme.json (có test canh).
E2E_CLIENT = {
    "clientId": E2E_CLIENT_ID,
    "name": "e2e-test (DEV/TEST ONLY)",
    "description": "DEV/TEST ONLY, created and deleted by eval/e2e/close_ticket.py. Token has aud=chat-ui like the BFF login token.",
    "enabled": True,
    "protocol": "openid-connect",
    "publicClient": True,
    "standardFlowEnabled": False,
    "directAccessGrantsEnabled": True,
    "serviceAccountsEnabled": False,
    "fullScopeAllowed": False,
    "defaultClientScopes": ["acme-claims", "aud-chat-ui"],
    "optionalClientScopes": [],
}
GRANT_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
ROUTER_MARK = "bộ định tuyến"  # có trong system prompt của router (agent/graph/nodes.py)

_SAFE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

HOP_HTTP = r"""
import sys, json, urllib.request as u, urllib.error as e
r = json.load(sys.stdin)
body = r.get("body")
req = u.Request(r["url"], data=body.encode() if body is not None else None,
                method=r["method"], headers=r.get("headers", {}))
try:
    resp = u.urlopen(req, timeout=r.get("timeout", 120))
except e.HTTPError as x:
    resp = x
print(json.dumps({"status": resp.status if hasattr(resp, "status") else resp.code,
                  "headers": dict(resp.headers)}), flush=True)
while True:
    line = resp.readline()
    if not line:
        break
    print(json.dumps({"b": line.decode("utf-8", "replace")}), flush=True)
"""

HOP_MCP = r"""
import sys, json, asyncio, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
r = json.load(sys.stdin)
async def main():
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + r["token"]},
                                  timeout=30) as hc:
        async with Client(streamable_http_client(r["url"], http_client=hc)) as c:
            res = await c.call_tool(r["tool"], r["args"], meta=r.get("meta"))
    data = res.structured_content
    if data is None:
        text = "".join(getattr(b, "text", "") for b in res.content)
        try:
            data = json.loads(text)
        except ValueError:
            data = {"text": text}
    print(json.dumps({"is_error": bool(res.is_error), "data": data}))
asyncio.run(main())
"""


# ----------------------------------------------------------------------------- kết quả
@dataclass
class Report:
    rows: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, bool(ok), detail))
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""),
            flush=True,
        )
        return bool(ok)

    def section(self, title: str) -> None:
        print(f"\n== {title}", flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for _, ok, _ in self.rows if not ok)


R = Report()


def secret(name: str) -> str:
    return (ROOT / "secrets" / name).read_text(encoding="utf-8").strip()


def lit(value: str) -> str:
    """Giá trị nhúng vào SQL: chỉ cho ký tự an toàn (mã ticket, uuid, tên)."""
    if not _SAFE.match(value):
        raise ValueError(f"unsafe sql literal: {value!r}")
    return value


# ----------------------------------------------------------------------------- hạ tầng
def compose(
    *args: str, stdin: str | None = None, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def psql_json(db: str, sql: str) -> list[dict[str, Any]]:
    wrapped = f"select coalesce(json_agg(t), '[]'::json) from ({sql}) t"
    p = compose(
        "exec",
        "-T",
        "-u",
        "postgres",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        db,
        "-tA",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        wrapped,
    )
    if p.returncode != 0:
        raise RuntimeError(f"psql {db} failed: {p.stderr.strip()[:300]}")
    return json.loads(p.stdout.strip() or "[]")


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    body: str

    def json(self) -> Any:
        return json.loads(self.body) if self.body.strip() else None

    def error_code(self) -> str | None:
        try:
            j = self.json()
        except ValueError:
            return None
        err = j.get("error") if isinstance(j, dict) else None
        return err.get("code") if isinstance(err, dict) else None


def hop(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any = None,
    service: str = "bff",
    timeout: float = 120,
) -> Resp:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": timeout,
        "body": None if body is None else json.dumps(body),
    }
    p = compose(
        "exec", "-T", service, "python", "-c", HOP_HTTP, stdin=json.dumps(req), timeout=timeout + 30
    )
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError(f"hop {method} {url} failed: {p.stderr.strip()[:300]}")
    lines = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    head, chunks = lines[0], "".join(x["b"] for x in lines[1:])
    return Resp(head["status"], head["headers"], chunks)


def mcp_call(
    token: str, tool: str, args: dict[str, Any], thread_id: str | None = None
) -> dict[str, Any]:
    req = {
        "token": token,
        "url": TICKETS_MCP,
        "tool": tool,
        "args": args,
        "meta": {"io.acme/thread_id": thread_id} if thread_id else None,
    }
    p = compose("exec", "-T", "agent", "python", "-c", HOP_MCP, stdin=json.dumps(req), timeout=90)
    if p.returncode != 0:
        # lỗi tầng giao vận (vd 401/403 từ MCP server) -> báo dạng transport error, không lộ chi tiết
        return {"transport_error": True, "stderr": p.stderr.strip()[-200:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


def _commit_failed(ev: list[tuple[str, dict[str, Any]]]) -> bool:
    """Resume với token xấu: agent vẫn kết thúc lượt (đáp lỗi) nhưng commit phải thất bại."""
    ends = [d for e, d in ev if e == "tool_end"]
    return bool(ends) and not any(d.get("ok") for d in ends)


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev, data = None, ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data += line[6:]
        if ev and data:
            out.append((ev, json.loads(data)))
    return out


def jwt_claims(token: str) -> dict[str, Any]:
    seg = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def tamper_payload(compact: str, mutate: Any) -> str:
    """Sửa payload của JWS/JWT nhưng giữ nguyên header + chữ ký (chữ ký phải thành sai)."""
    h, p, s = compact.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    mutate(claims)
    return ".".join([h, b64u(json.dumps(claims, separators=(",", ":")).encode()), s])


# ----------------------------------------------------------------------------- Keycloak
class Keycloak:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=20)
        self.chat_ui_secret = secret("bff_oidc_client_secret")
        self.agent_secret = secret("kc_agent_client_secret")
        self.passwords: dict[str, str] = {}
        self.user_ids: dict[str, str] = {}

    def _admin(self) -> dict[str, str]:
        r = self.http.post(
            f"{KC}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "admin",
                "password": secret("kc_admin_password"),
            },
        )
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def _client_uuids(self, h: dict[str, str]) -> list[str]:
        r = self.http.get(
            f"{KC}/admin/realms/{REALM}/clients", params={"clientId": E2E_CLIENT_ID}, headers=h
        )
        r.raise_for_status()
        return [c["id"] for c in r.json() if c["clientId"] == E2E_CLIENT_ID]

    def delete_client(self) -> bool:
        """Xoá client dev-only `e2e-test` (idempotent). Trả True nếu đã xoá."""
        h = self._admin()
        ids = self._client_uuids(h)
        for cid in ids:
            self.http.delete(
                f"{KC}/admin/realms/{REALM}/clients/{cid}", headers=h
            ).raise_for_status()
        return bool(ids)

    def ensure_test_setup(self, usernames: list[str]) -> bool:
        """Đảm bảo client dev-only `e2e-test` tồn tại (tạo qua Admin API) và đặt mật khẩu ngẫu nhiên
        cho các user test. Trả True nếu phải tạo client."""
        h = self._admin()
        created = False
        base = f"{KC}/admin/realms/{REALM}"
        if not self._client_uuids(h):
            self.http.post(f"{base}/clients", headers=h, json=E2E_CLIENT).raise_for_status()
            created = True
        for name in usernames:
            users = self.http.get(
                f"{base}/users", params={"username": name, "exact": "true"}, headers=h
            ).json()
            uid = users[0]["id"]
            pw = pysecrets.token_urlsafe(18)
            self.http.put(
                f"{base}/users/{uid}/reset-password",
                headers=h,
                json={"type": "password", "value": pw, "temporary": False},
            ).raise_for_status()
            self.passwords[name], self.user_ids[name] = pw, uid
        return created

    def login(self, username: str) -> str:
        r = self.http.post(
            f"{KC}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "e2e-test",
                "username": username,
                "password": self.passwords[username],
                "scope": "openid",
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def exchange(
        self, subject_token: str, audience: str, scope: str, *, client: str = "chat-ui"
    ) -> httpx.Response:
        sec = self.chat_ui_secret if client == "chat-ui" else self.agent_secret
        return self.http.post(
            f"{KC}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": GRANT_EXCHANGE,
                "client_id": client,
                "client_secret": sec,
                "subject_token": subject_token,
                "subject_token_type": TOKEN_TYPE,
                "requested_token_type": TOKEN_TYPE,
                "audience": audience,
                "scope": scope,
            },
        )

    def token_for(
        self, subject_token: str, audience: str, scope: str, *, client: str = "chat-ui"
    ) -> str:
        r = self.exchange(subject_token, audience, scope, client=client)
        r.raise_for_status()
        return r.json()["access_token"]


# ----------------------------------------------------------------------------- DB
def ticket_snapshot(code: str) -> dict[str, Any]:
    rows = psql_json(
        "tickets",
        (
            "select t.code, t.status, t.resolution, t.closed_by, t.closed_at, t.updated_at, "
            "(select count(*) from ticket_events e where e.ticket_id = t.id) as n_events "
            f"from tickets t where t.code = '{lit(code)}'"
        ),
    )
    return rows[0]


def pick_tickets(sub: str, n: int) -> list[str]:
    rows = psql_json(
        "tickets",
        (
            "select code from tickets where assignee_sub = "
            f"'{lit(sub)}' and status in ('open','in_progress','resolved') order by code limit {int(n)}"
        ),
    )
    return [r["code"] for r in rows]


def audit_rows(db: str, intent_id: str | None = None) -> list[dict[str, Any]]:
    sql = (
        f"select * from tool_audit where intent_id = '{lit(intent_id)}' order by id"
        if intent_id
        else None
    )
    return psql_json(db, sql) if sql else []


def verify_audit_chain(db: str) -> tuple[bool, str]:
    rows = psql_json(db, select_sql("tool_audit"))
    norm = []
    for r in rows:
        r = dict(r)
        r["ts"] = datetime.fromisoformat(r["ts"]).astimezone(UTC)
        for k in ("prev_hash", "hash"):
            r[k] = bytes.fromhex(r[k][2:])
        norm.append(r)
    ring = AuditKeyring.single(secret("audit_hmac_key"), 1)
    res = verify_chain(norm, ring)
    return res.ok, f"rows={res.checked} reason={res.reason} bad_id={res.bad_id}"


def same_state(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before == after


# ----------------------------------------------------------------------------- mock LLM
def mock_script(code: str, resolution: str) -> None:
    rules = [
        {
            "match": ROUTER_MARK,
            "times": 1,
            "text": json.dumps({"route": "ticket", "confidence": 0.95, "reason": "e2e"}),
        },
        {
            "needs_tool": "prepare_close_ticket",
            "tool": "prepare_close_ticket",
            "times": 1,
            "args": {"code": code, "resolution": resolution},
        },
    ]
    r = hop(
        "PUT", f"{MOCK}/__control/script", token=secret("gw_admin_token"), body={"rules": rules}
    )
    if r.status != 200:
        raise RuntimeError(f"mock script rejected: {r.status}")


def mock_reset() -> None:
    hop("DELETE", f"{MOCK}/__control", token=secret("gw_admin_token"))


# ----------------------------------------------------------------------------- luồng
@dataclass
class Prepared:
    code: str
    resolution: str
    thread_id: str
    interrupt_id: str
    intent_id: str
    intent_jws: str
    events: list[tuple[str, dict[str, Any]]]
    agent_token: str


def prepare_via_agent(kc: Keycloak, login: str, code: str, label: str) -> Prepared:
    """Giống BFF: tạo thread, gửi tin, đọc SSE tới interrupt."""
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    resolution = f"E2E {label} {uuid.uuid4().hex[:8]}: da xu ly xong yeu cau"
    t = hop("POST", f"{AGENT}/v1/threads", token=agent_tok, body={"title": f"e2e {label}"})
    assert t.status == 201, f"create_thread -> {t.status}"
    thread_id = t.json()["thread_id"]
    mock_script(code, resolution)
    text = f"đóng ticket {code}, lý do: {resolution}"
    run = hop(
        "POST",
        f"{AGENT}/v1/threads/{thread_id}/runs",
        token=agent_tok,
        body={"input": {"text": text}, "client_msg_id": "m" + uuid.uuid4().hex[:16]},
    )
    assert run.status == 200, f"run -> {run.status} {run.error_code()}"
    ev = parse_sse(run.body)
    names = [e for e, _ in ev]
    it = next((d for e, d in ev if e == "interrupt"), None)
    assert it is not None, (
        f"no interrupt; events={[n for n in names if n != 'token']} "
        f"tool_end={[d for e, d in ev if e == 'tool_end']} err={[d for e, d in ev if e == 'error']}"
    )
    pl = it["payload"]
    return Prepared(
        code,
        resolution,
        thread_id,
        it["interrupt_id"],
        pl["intent_id"],
        pl["intent_jws"],
        ev,
        agent_tok,
    )


def signer_verify(token: str, jws: str) -> Resp:
    return hop("POST", f"{SIGNER}/v1/intents/verify", token=token, body={"intent_jws": jws})


def signer_approve(token: str, jws: str) -> Resp:
    return hop("POST", f"{SIGNER}/v1/approvals", token=token, body={"intent_jws": jws})


def resume(agent_tok: str, prep: Prepared, decision: dict[str, Any]) -> Resp:
    return hop(
        "POST",
        f"{AGENT}/v1/threads/{prep.thread_id}/resume",
        token=agent_tok,
        body={"interrupt_id": prep.interrupt_id, "decision": decision},
    )


def rejected(r: Resp) -> bool:
    return r.status in (400, 401, 403, 409, 410, 422)


# ----------------------------------------------------------------------------- kịch bản
def scenario_positive(kc: Keycloak, user: str, sub: str, code: str) -> dict[str, Any]:
    R.section(f"A. Dương tính: {user} đóng {code}")
    start = datetime.now(UTC)
    before = ticket_snapshot(code)
    R.check(
        "A0 ticket chưa đóng trước khi chạy",
        before["status"] in ("open", "in_progress", "resolved"),
        before["status"],
    )

    login = kc.login(user)
    claims = jwt_claims(login)
    R.check(
        "A1 token đăng nhập: aud=chat-ui, sub khớp",
        claims.get("aud") == "chat-ui" and claims["sub"] == sub,
    )
    prep = prepare_via_agent(kc, login, code, "close")
    names = [e for e, _ in prep.events]
    route = next((d for e, d in prep.events if e == "route"), {})
    R.check(
        "A2 SSE: route=ticket (mock script ép định tuyến)",
        route.get("route") == "ticket",
        str(route),
    )
    tools = [
        (d.get("tool"), d.get("ok")) for e, d in prep.events if e in ("tool_start", "tool_end")
    ]
    R.check(
        "A3 SSE: prepare_close_ticket chạy ok, có interrupt, status=interrupted",
        ("prepare_close_ticket", None) in tools
        and ("prepare_close_ticket" in [d.get("tool") for e, d in prep.events if e == "tool_start"])
        and any(e == "tool_end" and d.get("ok") for e, d in prep.events)
        and next((d for e, d in prep.events if e == "done"), {}).get("status") == "interrupted",
        f"events={names}",
    )
    R.check(
        "A4 chưa ghi DB sau prepare (ticket y nguyên)", same_state(before, ticket_snapshot(code))
    )

    R.check(
        "A5 interrupt không chứa args/preview (chỉ định danh + JWS)",
        set(next(d for e, d in prep.events if e == "interrupt")["payload"])
        >= {"intent_id", "intent_jws", "op", "expires_at", "interrupt_id"},
    )

    signer_tok = kc.token_for(login, "approval-signer", "signer:approve")
    sc = jwt_claims(signer_tok)
    R.check(
        "A6 token signer: aud=approval-signer, azp=chat-ui, scope signer:approve",
        sc.get("aud") == "approval-signer"
        and sc.get("azp") == "chat-ui"
        and "signer:approve" in sc.get("scope", ""),
    )
    v = signer_verify(signer_tok, prep.intent_jws)
    card = v.json() if v.status == 200 else {}
    fields = {f.get("path"): f for f in (card.get("display", {}) or {}).get("display_fields", [])}
    flat = json.dumps(card, ensure_ascii=False)
    R.check(
        "A7 signer verify -> 200, card op=close_ticket, intent_id khớp",
        v.status == 200
        and card.get("op") == "close_ticket"
        and card.get("intent_id") == prep.intent_id,
        f"status={v.status}",
    )
    R.check(
        "A8 card hiển thị đủ mã ticket + resolution + trạng thái đổi sang closed",
        code in flat and prep.resolution in flat and "closed" in flat and len(fields) >= 3,
        f"display_fields={sorted(fields)}",
    )
    sha = card.get("intent_sha256", "")
    R.check(
        "A9 card có intent_sha256 (64 hex) và expires_at",
        bool(re.fullmatch(r"[0-9a-f]{64}", sha)) and bool(card.get("expires_at")),
    )

    ap = signer_approve(signer_tok, prep.intent_jws)
    apj = ap.json() if ap.status == 200 else {}
    R.check(
        "A10 signer approve bằng token CỦA CHÍNH USER -> 200 + approval_token",
        ap.status == 200 and bool(apj.get("approval_token")),
        f"status={ap.status}",
    )
    approval_token = apj["approval_token"]
    ac = jwt_claims(approval_token)
    R.check(
        "A11 approval token: sub=user, intent_sha256 khớp card, ttl <= 120s",
        ac.get("sub") == sub and ac.get("intent_sha256") == sha and ac["exp"] - ac["iat"] <= 120,
        f"keys={sorted(ac)}",
    )

    agent_tok2 = kc.token_for(login, "agent-service", "agent:invoke")
    rs = resume(agent_tok2, prep, {"type": "approve", "approval_token": approval_token})
    ev = parse_sse(rs.body) if rs.status == 200 else []
    done = next((d for e, d in ev if e == "done"), {})
    commit_ok = any(e == "tool_end" and d.get("ok") for e, d in ev)
    R.check(
        "A12 resume -> SSE: commit_intent ok, done.status=completed",
        rs.status == 200 and commit_ok and done.get("status") == "completed",
        f"status={rs.status} events={[e for e, _ in ev]}",
    )
    final = "".join(d.get("text", "") for e, d in ev if e == "token")
    R.check(
        "A13 câu trả lời cuối nhắc đã xong trên ticket",
        code in final and "Đã thực hiện" in final,
        final[:80],
    )

    # ---- đọc trạng thái thật
    after = ticket_snapshot(code)
    R.check("A14 DB tickets: status=closed", after["status"] == "closed", after["status"])
    R.check(
        "A15 DB tickets: resolution khớp, closed_by = sub của user",
        after["resolution"] == prep.resolution and after["closed_by"] == sub,
    )
    closed_at = datetime.fromisoformat(after["closed_at"]) if after["closed_at"] else None
    R.check(
        "A16 DB tickets: closed_at nằm trong lần chạy này",
        bool(closed_at) and closed_at >= start.replace(microsecond=0),
    )
    ev_rows = psql_json(
        "tickets",
        (
            "select e.* from ticket_events e join tickets t on t.id = e.ticket_id "
            f"where t.code = '{lit(code)}' and e.intent_id = '{lit(prep.intent_id)}' order by e.id"
        ),
    )
    row = ev_rows[0] if ev_rows else {}
    R.check(
        "A17 DB ticket_events: đúng 1 dòng close, actor=user, approval_jti, intent_sha256 khớp card",
        len(ev_rows) == 1
        and row.get("actor_sub") == sub
        and bool(row.get("approval_jti"))
        and row.get("intent_sha256") == sha
        and row.get("action", "").startswith("close"),
        f"n={len(ev_rows)} action={row.get('action')}",
    )
    R.check(
        "A18 DB ticket_events: before.status != closed, after.status = closed",
        (row.get("before") or {}).get("status") == before["status"]
        and (row.get("after") or {}).get("status") == "closed",
    )
    R.check("A19 ticket_events tăng đúng 1", after["n_events"] == before["n_events"] + 1)

    tool_audit = audit_rows("tickets", prep.intent_id)
    acts = sorted({(r["resource"], r["decision"]) for r in tool_audit})
    R.check(
        "A20 tool_audit(tickets): có prepare_close_ticket và commit_intent cho intent này",
        any(a == "prepare_close_ticket" for a, _ in acts)
        and any(a == "commit_intent" for a, _ in acts),
        str(acts),
    )
    R.check(
        "A21 tool_audit(tickets): end_user_sub = user",
        all(r["end_user_sub"] == sub for r in tool_audit) and bool(tool_audit),
    )
    ok, d = verify_audit_chain("tickets")
    R.check("A22 hash-chain tool_audit(tickets) verify OK (HMAC, toàn bảng)", ok, d)
    ok, d = verify_audit_chain("knowledge")
    R.check(
        "A23 hash-chain tool_audit(knowledge) verify OK (luồng này không gọi docs-mcp nên chỉ kiểm chuỗi hiện có)",
        ok,
        d,
    )

    cost = next((d for e, d in prep.events if e == "cost"), {})
    rids = [c["request_id"] for c in cost.get("calls", []) if c.get("request_id")]
    got: list[dict[str, Any]] = []
    for _ in range(20):  # sink đẩy batch định kỳ
        got = (
            psql_json(
                "gateway",
                (
                    "select request_id, end_user_sub, status_code, alias, cache from usage_events where request_id in ("
                    + ",".join(f"'{lit(x)}'" for x in rids)
                    + ")"
                ),
            )
            if rids
            else []
        )
        if len(got) >= len(rids):
            break
        time.sleep(1)
    R.check(
        "A24 usage_events: có dòng cho MỌI call LLM của lượt (router + agent), status 200",
        len(rids) >= 2 and len(got) == len(rids) and all(g["status_code"] == 200 for g in got),
        f"agent_calls={len(rids)} rows={len(got)} aliases={[g['alias'] for g in got]} cache={[g['cache'] for g in got]}",
    )
    R.check(
        "A25 usage_events: end_user_sub = user",
        bool(got) and all(g["end_user_sub"] == sub for g in got),
    )

    # ---- replay
    rs2 = resume(agent_tok2, prep, {"type": "approve", "approval_token": approval_token})
    R.check(
        "A26 replay: resume lần 2 cùng interrupt bị từ chối (409)",
        rs2.status == 409,
        f"status={rs2.status} code={rs2.error_code()}",
    )
    tk = kc.token_for(agent_tok2, "tickets-mcp", "tickets:write", client="agent-service")
    rp = mcp_call(
        tk,
        "commit_intent",
        {"intent_id": prep.intent_id, "approval_token": approval_token},
        prep.thread_id,
    )
    err = rp.get("data") or {}
    R.check(
        "A27 replay: commit_intent lại với CÙNG approval_token -> approval_replayed (jti)",
        rp.get("is_error") is True and err.get("code") == "approval_replayed",
        f"rp={str(rp)[:300]}",
    )
    R.check(
        "A28 sau replay DB y nguyên (không đóng/ghi event lần 2)",
        same_state(after, ticket_snapshot(code)),
    )
    return {"code": code, "intent_id": prep.intent_id, "login": login}


def scenario_wrong_user(kc: Keycloak, user: str, other: str, code: str) -> None:
    R.section(f"B. Sai chủ thể: {other} và token sai aud cố duyệt intent của {user} ({code})")
    login, login_b = kc.login(user), kc.login(other)
    prep = prepare_via_agent(kc, login, code, "wrong-user")
    before = ticket_snapshot(code)
    n_audit = len(audit_rows("tickets", prep.intent_id))

    tok_b = kc.token_for(login_b, "approval-signer", "signer:approve")
    r = signer_approve(tok_b, prep.intent_jws)
    R.check(
        "B1 user KHÁC (token hợp lệ aud=approval-signer) approve intent của user A -> bị từ chối",
        rejected(r) and r.status != 200,
        f"status={r.status} code={r.error_code()}",
    )
    r = signer_verify(tok_b, prep.intent_jws)
    R.check(
        "B2 user KHÁC verify (xem thẻ) intent của A -> bị từ chối (sub mismatch)",
        rejected(r),
        f"status={r.status} code={r.error_code()}",
    )

    agent_tok_a = kc.token_for(login, "agent-service", "agent:invoke")
    r = signer_approve(agent_tok_a, prep.intent_jws)
    R.check(
        "B3 token agent (aud=agent-service) gửi tới signer /v1/approvals -> 401/403",
        r.status in (401, 403),
        f"status={r.status} code={r.error_code()}",
    )
    r = signer_verify(agent_tok_a, prep.intent_jws)
    R.check(
        "B4 token agent gửi tới signer /v1/intents/verify -> 401/403",
        r.status in (401, 403),
        f"status={r.status}",
    )
    r = signer_approve(login, prep.intent_jws)
    R.check(
        "B5 token đăng nhập (aud=chat-ui) tới signer -> 401/403",
        r.status in (401, 403),
        f"status={r.status} code={r.error_code()}",
    )
    tk_a = kc.token_for(agent_tok_a, "tickets-mcp", "tickets:write", client="agent-service")
    r = signer_approve(tk_a, prep.intent_jws)
    R.check(
        "B6 token aud=tickets-mcp (sai audience) tới signer -> 401/403",
        r.status in (401, 403),
        f"status={r.status}",
    )
    ex = kc.exchange(agent_tok_a, "approval-signer", "signer:approve", client="agent-service")
    R.check(
        "B7 Keycloak: agent-service exchange sang approval-signer bị từ chối",
        ex.status_code in (400, 401, 403),
        f"status={ex.status_code}",
    )
    r = hop("POST", f"{SIGNER}/v1/approvals", body={"intent_jws": prep.intent_jws})
    R.check("B8 không có token -> 401", r.status == 401, f"status={r.status}")

    r = hop(
        "GET",
        f"{AGENT}/v1/threads/{prep.thread_id}/messages",
        token=kc.token_for(login_b, "agent-service", "agent:invoke"),
    )
    R.check("B9 user khác không đọc được thread của A (404)", r.status == 404, f"status={r.status}")
    r = hop(
        "POST",
        f"{AGENT}/v1/threads/{prep.thread_id}/resume",
        token=kc.token_for(login_b, "agent-service", "agent:invoke"),
        body={"interrupt_id": prep.interrupt_id, "decision": {"type": "reject"}},
    )
    R.check(
        "B10 user khác không resume được thread của A (404)", r.status == 404, f"status={r.status}"
    )
    r = resume(agent_tok_a, prep, {"type": "approve", "approval_token": "x" * 40})
    ev = parse_sse(r.body) if r.status == 200 else []
    R.check(
        "B11 resume approve với approval_token rác -> commit bị từ chối (tool_end ok=false)",
        bool(ev) and _commit_failed(ev),
        f"status={r.status} tail={[(e, d) for e, d in ev if e in ('tool_end', 'done', 'error')]}",
    )

    R.check("B12 DB ticket y nguyên sau mọi lần thử", same_state(before, ticket_snapshot(code)))
    after_audit = audit_rows("tickets", prep.intent_id)
    R.check(
        "B13 tool_audit: không có commit_intent THÀNH CÔNG cho intent này",
        not any(r["resource"] == "commit_intent" and r["decision"] == "allow" for r in after_audit),
        str(sorted({(r["resource"], r["decision"]) for r in after_audit})) + f" (trước {n_audit})",
    )


def scenario_tamper(kc: Keycloak, user: str, code: str, other_code: str) -> None:
    R.section(f"C. Giả mạo: sửa intent / approval token / lẫn intent ({code}, {other_code})")
    login = kc.login(user)
    prep = prepare_via_agent(kc, login, code, "tamper")
    prep2 = prepare_via_agent(kc, login, other_code, "tamper-x")
    b1, b2 = ticket_snapshot(code), ticket_snapshot(other_code)
    signer_tok = kc.token_for(login, "approval-signer", "signer:approve")

    bad = tamper_payload(
        prep.intent_jws,
        lambda c: (
            c.__setitem__("args", {**c["args"], "resolution": "doi noi dung sau khi ky"})
            if "args" in c
            else c.__setitem__("tamper", 1)
        ),
    )
    r = signer_approve(signer_tok, bad)
    R.check(
        "C1 intent_jws bị sửa payload (chữ ký/sha sai) -> signer từ chối approve",
        rejected(r),
        f"status={r.status} code={r.error_code()}",
    )
    r = signer_verify(signer_tok, bad)
    R.check(
        "C2 intent_jws bị sửa payload -> signer từ chối verify",
        rejected(r),
        f"status={r.status} code={r.error_code()}",
    )

    ap = signer_approve(signer_tok, prep.intent_jws).json()["approval_token"]
    forged = tamper_payload(ap, lambda c: c.__setitem__("intent_sha256", "0" * 64))
    agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
    tk = kc.token_for(agent_tok, "tickets-mcp", "tickets:write", client="agent-service")
    rp = mcp_call(
        tk, "commit_intent", {"intent_id": prep.intent_id, "approval_token": forged}, prep.thread_id
    )
    err = rp.get("data") or {}
    R.check(
        "C3 approval token bị sửa intent_sha256 -> commit_intent bị từ chối",
        rp.get("is_error") is True and bool(err.get("code")),
        f"rp={str(rp)[:300]}",
    )

    # token hợp lệ của intent X (prep2) dùng cho intent khác (prep): sha/intent không khớp
    ap2 = signer_approve(signer_tok, prep2.intent_jws).json()["approval_token"]
    rp = mcp_call(
        tk, "commit_intent", {"intent_id": prep.intent_id, "approval_token": ap2}, prep.thread_id
    )
    err = rp.get("data") or {}
    R.check(
        "C4 approval token của intent khác -> commit_intent bị từ chối",
        rp.get("is_error") is True and bool(err.get("code")),
        f"rp={str(rp)[:300]}",
    )

    # đường agent: resume bằng token của intent khác
    rs = resume(agent_tok, prep, {"type": "approve", "approval_token": ap2})
    ev = parse_sse(rs.body) if rs.status == 200 else []
    R.check(
        "C5 resume bằng approval token của intent khác -> commit bị từ chối (tool_end ok=false)",
        bool(ev) and _commit_failed(ev),
        f"tail={[(e, d) for e, d in ev if e in ('tool_end', 'done', 'error')]}",
    )

    R.check(
        "C6 DB cả hai ticket y nguyên",
        same_state(b1, ticket_snapshot(code)) and same_state(b2, ticket_snapshot(other_code)),
    )
    a1, a2 = audit_rows("tickets", prep.intent_id), audit_rows("tickets", prep2.intent_id)
    R.check(
        "C7 tool_audit: không commit_intent thành công cho cả hai intent",
        not any(r["resource"] == "commit_intent" and r["decision"] == "allow" for r in a1 + a2),
    )


@dataclass
class ExpiryCase:
    prep: Prepared
    login: str
    user: str
    approval_token: str
    before: dict[str, Any]
    expires_at: str


def expiry_begin(kc: Keycloak, user: str, code: str) -> ExpiryCase:
    R.section(f"D. Hết hạn: chuẩn bị intent cho {code} (kiểm lại sau TTL ở cuối lần chạy)")
    login = kc.login(user)
    prep = prepare_via_agent(kc, login, code, "expiry")
    st = kc.token_for(login, "approval-signer", "signer:approve")
    ap = signer_approve(st, prep.intent_jws)
    R.check(
        "D0 intent mới duyệt được khi còn hạn (lấy approval token để dùng muộn)",
        ap.status == 200,
        f"status={ap.status}",
    )
    exp = next(d for e, d in prep.events if e == "interrupt")["payload"]["expires_at"]
    return ExpiryCase(prep, login, user, ap.json()["approval_token"], ticket_snapshot(code), exp)


def expiry_finish(kc: Keycloak, case: ExpiryCase) -> None:
    R.section(f"D. Hết hạn: chờ intent {case.prep.code} quá hạn rồi thử lại")
    exp = datetime.fromisoformat(case.expires_at.replace("Z", "+00:00"))
    case.login = kc.login(case.user)  # token đăng nhập cũ đã hết hạn sau ~5 phút chờ
    st = kc.token_for(case.login, "approval-signer", "signer:approve")
    deadline = time.time() + 400
    last = signer_verify(st, case.prep.intent_jws)
    while last.status == 200 and time.time() < deadline:
        left = max(5.0, (exp - datetime.now(UTC)).total_seconds() + 3)
        print(f"  ... intent còn hạn, chờ {left:.0f}s (expires_at={case.expires_at})", flush=True)
        time.sleep(min(left, 60))
        case.login = kc.login(case.user)
        st = kc.token_for(case.login, "approval-signer", "signer:approve")
        last = signer_verify(st, case.prep.intent_jws)
    R.check(
        "D1 sau TTL: signer verify -> 410 intent_expired",
        last.status == 410 and last.error_code() == "intent_expired",
        f"status={last.status} code={last.error_code()}",
    )
    r = signer_approve(st, case.prep.intent_jws)
    R.check(
        "D2 sau TTL: signer approve -> 410 intent_expired (không ký)",
        r.status == 410 and r.error_code() == "intent_expired",
        f"status={r.status} code={r.error_code()}",
    )
    agent_tok = kc.token_for(case.login, "agent-service", "agent:invoke")
    rs = resume(agent_tok, case.prep, {"type": "approve", "approval_token": case.approval_token})
    ev = parse_sse(rs.body) if rs.status == 200 else []
    errs = [d.get("code") for e, d in ev if e == "error"]
    R.check(
        "D3 resume với approval token cũ sau TTL -> error intent_expired/approval_expired, không completed",
        bool(ev)
        and _commit_failed(ev)
        and all(c in ("intent_expired", "approval_expired", "intent_not_found") for c in errs),
        f"errors={errs}",
    )
    R.check("D4 DB ticket y nguyên", same_state(case.before, ticket_snapshot(case.prep.code)))
    a = audit_rows("tickets", case.prep.intent_id)
    R.check(
        "D5 tool_audit: không commit_intent thành công",
        not any(r["resource"] == "commit_intent" and r["decision"] == "allow" for r in a),
    )


# ----------------------------------------------------------------------------- main
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--user", default="an.nguyen", help="user thực hiện (phải là assignee của ticket)"
    )
    ap.add_argument("--other-user", default="binh.tran", help="user khác để thử duyệt trái phép")
    ap.add_argument(
        "--skip-expiry", action="store_true", help="bỏ ca hết hạn (mất ~5 phút chờ TTL intent)"
    )
    ap.add_argument(
        "--keep-client",
        action="store_true",
        help="giữ client e2e-test sau khi chạy (debug); mặc định xoá ở cuối",
    )
    args = ap.parse_args()
    host = urlparse(KC).hostname or ""
    if host not in DEV_KC_HOSTS and os.environ.get("E2E_ALLOW") != "1":
        print(
            f"Từ chối chạy: Keycloak host {host!r} không phải dev {sorted(DEV_KC_HOSTS)} (đặt E2E_ALLOW=1 để ép)",
            file=sys.stderr,
        )
        return 2
    t0 = time.time()
    print(
        f"E2E close_ticket  run_id={uuid.uuid4().hex[:8]}  user={args.user}  other={args.other_user}"
    )

    kc = Keycloak()
    try:
        return _run(args, kc, t0)
    finally:
        if args.keep_client:
            print(f"keycloak: GIỮ client {E2E_CLIENT_ID} (--keep-client)")
        else:
            try:
                gone = kc.delete_client()
                print(f"keycloak: client {E2E_CLIENT_ID} {'ĐÃ XOÁ' if gone else 'không còn'}")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  WARN: không xoá được client {E2E_CLIENT_ID}: {type(exc).__name__}",
                    file=sys.stderr,
                )


def _run(args: argparse.Namespace, kc: Keycloak, t0: float) -> int:
    created = kc.ensure_test_setup([args.user, args.other_user])
    print(
        f"keycloak: client e2e-test {'ĐÃ TẠO' if created else 'đã có'}; mật khẩu test đặt lại (chỉ trong bộ nhớ)"
    )
    sub = kc.user_ids[args.user]
    codes = pick_tickets(sub, 6)
    if len(codes) < 5:
        print("Không đủ ticket open/in_progress của user để chạy (cần >= 5)", file=sys.stderr)
        return 2
    print(
        f"ticket chọn: dương tính={codes[0]} sai-chủ-thể={codes[1]} giả-mạo={codes[2]},{codes[3]} hết-hạn={codes[4]}"
    )

    case: ExpiryCase | None = None
    try:
        for fn, label in (
            (lambda: scenario_positive(kc, args.user, sub, codes[0]), "A"),
            (lambda: scenario_wrong_user(kc, args.user, args.other_user, codes[1]), "B"),
            (lambda: scenario_tamper(kc, args.user, codes[2], codes[3]), "C"),
        ):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - ghi lỗi kịch bản rồi chạy tiếp
                R.check(
                    f"{label}-scenario hoàn tất không lỗi",
                    False,
                    f"{type(exc).__name__}: {str(exc)[:300]}",
                )
        if not args.skip_expiry:
            try:
                case = expiry_begin(kc, args.user, codes[4])
            except Exception as exc:  # noqa: BLE001
                R.check("D-scenario chuẩn bị", False, f"{type(exc).__name__}: {str(exc)[:300]}")
        if case:
            try:
                expiry_finish(kc, case)
            except Exception as exc:  # noqa: BLE001
                R.check("D-scenario kết thúc", False, f"{type(exc).__name__}: {str(exc)[:300]}")
        ok, d = verify_audit_chain("tickets")
        R.check("Z1 hash-chain tool_audit(tickets) vẫn verify OK sau toàn bộ ca âm", ok, d)
    finally:
        try:
            mock_reset()
        except Exception:  # noqa: BLE001
            print("  WARN: không reset được kịch bản mock-provider", file=sys.stderr)

    print("\n== TỔNG KẾT ==")
    for name, ok, _detail in R.rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(
        f"\n{len(R.rows) - R.failed}/{len(R.rows)} assertion đạt; {int(time.time() - t0)}s; expiry={'bỏ qua' if args.skip_expiry else 'đã chạy'}"
    )
    return 1 if R.failed else 0


if __name__ == "__main__":
    sys.exit(main())
