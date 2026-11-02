"""Chạy quét canary trên stack compose THẬT (profile `obs`, `OTEL_EXPORTER_OTLP_ENDPOINT` đã đặt).

Luồng: đăng nhập BFF như trình duyệt (Keycloak form) -> đặt kịch bản mock LLM để router chọn `docs` và
agent gọi `search_documents` với câu hỏi chứa canary -> POST /api/chat với `traceparent` do script tạo
-> lấy trace từ Tempo API theo đúng trace_id -> quét log mọi service và trace. Có canary là đỏ (exit 1);
thiếu hop BFF/agent/gateway/docs-mcp trong trace cũng đỏ.

Tác dụng phụ (dev): đặt lại mật khẩu ngẫu nhiên của user test qua Admin API (giống eval/e2e), đặt kịch bản
cho mock-provider rồi reset. Từ chối chạy nếu Keycloak không phải localhost (trừ `CANARY_ALLOW=1`).
Không in nội dung câu hỏi, token hay mật khẩu.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .scan import Finding, missing_hops, new_canary, scan_text, summarize_trace

ROOT = Path(__file__).resolve().parents[2]
KC = "http://localhost:8080"
REALM = "acme"
BFF = "http://localhost:8300"
TEMPO = "http://localhost:3200"
REQUIRED_HOPS = ("bff", "agent", "gateway", "docs-mcp")
ROUTER_MARK = "bộ định tuyến"  # có trong system prompt của router (agent/graph/nodes.py)

HOP_PUT = r"""
import sys, json, urllib.request as u
r = json.load(sys.stdin)
req = u.Request(r["url"], data=json.dumps(r["body"]).encode() if r.get("body") is not None else None,
                method=r["method"], headers={"Authorization": "Bearer " + r["token"],
                                             "Content-Type": "application/json"})
print(u.urlopen(req, timeout=20).status)
"""


def secret(name: str) -> str:
    return (ROOT / "secrets" / name).read_text(encoding="utf-8").strip()


def compose(*args: str, stdin: str | None = None, timeout: float = 180) -> str:
    p = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"docker compose {args[0]} lỗi (mã {p.returncode})")
    return p.stdout + p.stderr


def mock_control(method: str, path: str, body: Any = None) -> None:
    req = {
        "method": method,
        "url": f"http://mock-provider:8900{path}",
        "token": secret("gw_admin_token"),
        "body": body,
    }
    compose("exec", "-T", "bff", "python", "-c", HOP_PUT, stdin=json.dumps(req))


def mock_script(canary: str) -> None:
    rules = [
        {
            "match": ROUTER_MARK,
            "times": 1,
            "text": json.dumps({"route": "docs", "confidence": 0.95, "reason": "canary"}),
        },
        {
            "needs_tool": "search_documents",
            "tool": "search_documents",
            "times": 1,
            "args": {"query": f"{canary} thời hạn nộp hồ sơ", "top_k": 3},
        },
    ]
    mock_control("PUT", "/__control/script", {"rules": rules})


def set_test_password(http: httpx.Client, username: str) -> str:
    r = http.post(
        f"{KC}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": secret("kc_admin_password"),
        },
    )
    r.raise_for_status()
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    base = f"{KC}/admin/realms/{REALM}"
    users = http.get(f"{base}/users", params={"username": username, "exact": "true"}, headers=h)
    uid = users.json()[0]["id"]
    pw = secrets.token_urlsafe(18)
    http.put(
        f"{base}/users/{uid}/reset-password",
        headers=h,
        json={"type": "password", "value": pw, "temporary": False},
    ).raise_for_status()
    return pw


def _local(url: str) -> str:
    """Keycloak công bố host `keycloak.acme.local`; từ máy chạy script gọi qua localhost."""
    return url.replace("keycloak.acme.local", "localhost")


class _PlainCookies:
    """Client Keycloak giữ cookie thủ công: Keycloak đặt `Secure` dù chạy http (dev), nên cookie jar
    của httpx không gửi lại qua http."""

    def __init__(self) -> None:
        self._http = httpx.Client(follow_redirects=False, timeout=30)
        self._jar: dict[str, str] = {}

    def _send(self, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self._jar.items())}
        r = self._http.request(method, url, headers=headers, **kw)
        for h in r.headers.get_list("set-cookie"):
            name, _, rest = h.partition("=")
            self._jar[name.strip()] = rest.split(";", 1)[0]
        return r

    def get(self, url: str) -> httpx.Response:
        return self._send("GET", url)

    def post(self, url: str, data: dict[str, str]) -> httpx.Response:
        return self._send("POST", url, data=data)


def login_bff(username: str, password: str) -> httpx.Client:
    """Đăng nhập BFF như trình duyệt; trả client giữ cookie phiên."""
    c = httpx.Client(base_url=BFF, follow_redirects=False, timeout=30)
    r = c.get("/auth/login")
    url = _local(r.headers["location"])
    kc = _PlainCookies()
    page = kc.get(url)
    m = re.search(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', page.text)
    if not m:
        m = re.search(r'action="([^"]+)"[^>]*method="post"', page.text)
    if not m:
        raise RuntimeError("không tìm thấy form đăng nhập Keycloak")
    action = _local(m.group(1).replace("&amp;", "&"))
    r = kc.post(action, data={"username": username, "password": password})
    for _ in range(5):
        loc = r.headers.get("location")
        if r.status_code not in (301, 302, 303) or not loc:
            break
        loc = _local(loc)
        if urlparse(loc).netloc == urlparse(BFF).netloc:
            cb = c.get(loc.removeprefix(BFF))
            if cb.status_code not in (302, 303) or "/login-error" in cb.headers.get("location", ""):
                raise RuntimeError("BFF callback thất bại")
            break
        r = kc.get(urljoin(url, loc))
    if "sid" not in c.cookies and "__Host-sid" not in c.cookies:
        raise RuntimeError("không có cookie phiên BFF sau đăng nhập")
    return c


def chat(c: httpx.Client, canary: str, traceparent: str) -> dict[str, int]:
    csrf = c.cookies.get("csrf") or c.cookies.get("__Host-csrf") or ""
    events: dict[str, int] = {}
    import uuid

    body = {"text": f"{canary} thời hạn nộp hồ sơ là bao lâu?", "client_msg_id": str(uuid.uuid4())}
    with c.stream(
        "POST",
        "/api/chat",
        json=body,
        headers={"Origin": BFF, "x-csrf-token": csrf, "traceparent": traceparent},
        timeout=120,
    ) as r:
        if r.status_code != 200:
            raise RuntimeError(f"/api/chat trả {r.status_code}")
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
                events[name] = events.get(name, 0) + 1
    return events


def fetch_trace(trace_id: str, *, wait_s: float) -> dict[str, Any] | None:
    """Poll Tempo tới khi số span ổn định (BatchSpanProcessor gửi theo lô)."""
    deadline = time.monotonic() + wait_s
    best: dict[str, Any] | None = None
    best_n = 0
    stable = 0
    while time.monotonic() < deadline:
        r = httpx.get(f"{TEMPO}/api/traces/{trace_id}", timeout=10)
        if r.status_code == 200:
            doc = r.json()
            n = summarize_trace(doc).spans
            stable = stable + 1 if n == best_n else 0
            best, best_n = doc, n
            if n and stable >= 2:
                return best
        time.sleep(3)
    return best


def scan_logs(canary: str, since: str) -> list[Finding]:
    """Log của mọi service trong compose (kể cả service đã dừng) từ lúc bắt đầu chạy."""
    services = (
        compose("config", "--services").split()
        + compose("--profile", "obs", "--profile", "tickets", "config", "--services").split()
    )
    out: list[Finding] = []
    for svc in sorted(set(services)):
        try:
            text = compose(
                "--profile",
                "obs",
                "--profile",
                "tickets",
                "logs",
                "--no-color",
                "--since",
                since,
                svc,
            )
        except RuntimeError:
            continue
        f = scan_text(f"log:{svc}", text, canary)
        if f:
            out.append(f)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.canary", description=__doc__)
    ap.add_argument("--user", default="an.nguyen")
    ap.add_argument("--wait", type=float, default=45.0, help="giây chờ trace về Tempo")
    ap.add_argument("--hops", default=",".join(REQUIRED_HOPS))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

    if urlparse(KC).hostname != "localhost" and os.environ.get("CANARY_ALLOW") != "1":
        print("từ chối: Keycloak không phải localhost", file=sys.stderr)
        return 2
    canary = new_canary()
    trace_id, span_id = secrets.token_hex(16), secrets.token_hex(8)
    traceparent = f"00-{trace_id}-{span_id}-01"
    since = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"canary dài {len(canary)} ký tự (không in); trace_id={trace_id}", flush=True)

    http = httpx.Client(timeout=20)
    pw = set_test_password(http, args.user)
    bff = login_bff(args.user, pw)
    mock_script(canary)
    try:
        events = chat(bff, canary, traceparent)
    finally:
        mock_control("DELETE", "/__control")
    print(f"SSE: {events}", flush=True)

    findings: list[Finding] = []
    doc = fetch_trace(trace_id, wait_s=args.wait)
    summary = summarize_trace(doc or {})
    print(f"trace {trace_id}: {summary.spans} span, dịch vụ {sorted(summary.services)}", flush=True)
    for name in sorted(set(summary.span_names)):
        print(f"  span {name}")
    if doc is not None:
        f = scan_text("trace:tempo", json.dumps(doc, ensure_ascii=False), canary)
        if f:
            findings.append(f)
    findings += scan_logs(canary, since)

    required = tuple(h for h in args.hops.split(",") if h)
    missing = missing_hops(summary, required)
    for f in findings:
        print(f"  [RÒ RỈ] canary xuất hiện {f.count} lần ở {f.where}")
    if missing:
        print(f"  [THIẾU HOP] {missing}")
    ok = not findings and not missing and summary.spans > 0
    print("CANARY: " + ("XANH (0 chỗ rò, đủ hop)" if ok else "ĐỎ"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
