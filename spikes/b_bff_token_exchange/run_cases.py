"""Spike B: BFF -> token exchange -> agent-service / approval-signer tren Keycloak that.

Chay: uv run --no-project --with fastapi --with uvicorn --with httpx --with "pyjwt[crypto]" --with langgraph \
        python spikes/b_bff_token_exchange/run_cases.py [--no-cleanup]
"""
import importlib.metadata as md
import json, os, re, secrets as pysecrets, subprocess, sys, tempfile, threading, time, zipfile
from pathlib import Path
from urllib.parse import urljoin
import html
import httpx
import uvicorn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common, signer, agent, bff  # noqa: E402

REPO = HERE.parent.parent
BFF_PORT = int(os.environ.get("SPIKE_B_BFF_PORT", 8310))
SIGNER_PORT = int(os.environ.get("SPIKE_B_SIGNER_PORT", 8311))
AGENT_PORT = int(os.environ.get("SPIKE_B_AGENT_PORT", 8312))
BFF_BASE = bff.PUBLIC_BASE

SCRUB: list = []  # chuoi bi mat can che trong output


class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf8")
        self.o = sys.stdout

    def write(self, s):
        s = common.JWT_RE.sub("<jwt-redacted>", s)
        for x in SCRUB:
            s = s.replace(x, "<secret-redacted>")
        self.f.write(s); self.o.write(s)

    def isatty(self):
        return False

    def flush(self):
        self.f.flush(); self.o.flush()


RESULTS: list = []


def rec(code, desc, ok, detail=""):
    tag = "INFO" if ok is None else ("PASS" if ok else "FAIL")
    RESULTS.append((code, tag))
    print(f"[{code}] {desc} -> {detail}  <{tag}>")


def J(o):
    return json.dumps(o, ensure_ascii=False, default=str)


def kc(sub, env=None, check=True):
    """Chay kc_setup.sh trong container keycloak (mat khau truyen qua stdin, khong qua argv/file)."""
    script = (HERE / "kc_setup.sh").read_text(encoding="utf8")
    pre = "".join(f"export {k}='{v}'\n" for k, v in (env or {}).items())
    p = subprocess.run(["docker", "compose", "exec", "-T", "keycloak", "bash", "-s", sub],
                       input=(pre + script).encode(), cwd=REPO, capture_output=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"kc_setup {sub} failed rc={p.returncode}: {err[-500:]}")
    return out


# ---------- servers ----------
def start(app, port):
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            return srv
        time.sleep(0.1)
    raise RuntimeError(f"server {port} not started")


# ---------- "trinh duyet" ----------
class HostRewrite(httpx.HTTPTransport):
    """Host may host khong resolve keycloak.acme.local -> noi toi 127.0.0.1 nhung GIU header Host
    (cookie jar van theo domain keycloak.acme.local nhu trinh duyet that)."""

    def handle_request(self, request):
        if request.url.host in ("keycloak.acme.local", "localhost"):
            # tao request MOI (khong sua request goc, neu khong cookie jar se luu theo 127.0.0.1)
            request = httpx.Request(request.method, request.url.copy_with(host="127.0.0.1"), headers=request.headers,
                                    stream=request.stream, extensions=request.extensions)
        return super().handle_request(request)


class Browser:
    def __init__(self):
        self.log = []  # moi response nhan tu BFF
        self.c = httpx.Client(transport=HostRewrite(), follow_redirects=False, timeout=20,
                              event_hooks={"response": [self._hook]})
        self.callback = None

    def _hook(self, r):
        if r.url.port == BFF_PORT:
            r.read()
            hdr = "\n".join(f"{k}: {v}" for k, v in r.headers.multi_items())
            self.log.append((str(r.request.url), r.status_code, hdr, r.text))

    def login(self, user, pw):
        url = f"{BFF_BASE}/auth/login"
        for _ in range(12):
            r = self.c.get(url) if not isinstance(url, tuple) else self.c.post(url[0], data=url[1])
            if r.status_code in (301, 302, 303, 307):
                loc = urljoin(str(r.url), r.headers["location"])
                if loc.startswith(f"{BFF_BASE}/auth/callback"):
                    self.callback = self.c.get(loc)
                    return self.callback
                url = loc
                continue
            m = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', r.text) or \
                re.search(r'<form[^>]*action="([^"]+)"[^>]*id="kc-form-login"', r.text)
            if not m:
                em = re.search(r'id="kc-error-message".*?<p[^>]*>(.*?)</p>', r.text, re.S)
                raise RuntimeError(f"khong thay form login: {r.status_code} url={r.request.url} kc-error={em.group(1).strip() if em else r.text[-300:]}")
            url = (html.unescape(m.group(1)), {"username": user, "password": pw, "credentialId": ""})
        raise RuntimeError("qua nhieu redirect")

    def sid(self):
        for ck in self.c.cookies.jar:
            if ck.name == bff.COOKIE:
                return ck.value

    def session(self):
        return bff.SESSIONS[self.sid()]

    def api(self, method, path, body=None, csrf=True):
        h = {}
        if csrf:
            h["X-CSRF-Token"] = self.c.get(f"{BFF_BASE}/api/me").json()["csrf_token"]
        return self.c.request(method, f"{BFF_BASE}{path}", json=body, headers=h)


def err_of(body):
    return f"{body.get('error')}: {body.get('error_description')}" if isinstance(body, dict) else str(body)


def scan_browser(browsers, label):
    toks = []
    for b in browsers:
        for t in b.session()["tokens"].values():
            toks.append(t)
    hits = []
    for b in browsers:
        for url, st, hdr, body in b.log:
            blob = hdr + "\n" + body
            if common.JWT_RE.search(blob):
                hits.append((url, "regex JWT"))
            for t in toks:
                if t in blob or t.split(".")[2][:30] in blob:
                    hits.append((url, "token that trong session"))
    n = sum(len(b.log) for b in browsers)
    rec(label, f"quet {n} response BFF->trinh duyet (body+header), regex JWT + {len(toks)} token that trong session",
        not hits, f"{len(hits)} hit {hits[:3] if hits else ''}")


def b64u_json(s):
    import base64
    return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))


def tamper_decision(jws, new):
    import base64
    h, p, s = jws.split(".")
    d = b64u_json(p); d["decision"] = new
    p2 = base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return f"{h}.{p2}.{s}"


def agent_call(tok, path, body):
    return httpx.post(f"http://127.0.0.1:{AGENT_PORT}{path}", json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=30)


def signer_call(tok, intent, decision="approve"):
    return httpx.post(f"http://127.0.0.1:{SIGNER_PORT}/v1/approvals", json={"intent": intent, "decision": decision},
                      headers={"Authorization": f"Bearer {tok}"} if tok else {}, timeout=15)


def claims_or_err(st, body):
    if st == 200:
        return "HTTP 200 claims=" + J(common.show_claims(common.claims_unverified(body["access_token"])))
    return f"HTTP {st} {J({k: body.get(k) for k in ('error', 'error_description')})}"


def run():
    pw_an, pw_binh = pysecrets.token_urlsafe(18), pysecrets.token_urlsafe(18)
    SCRUB.extend([pw_an, pw_binh, common.secret("bff_oidc_client_secret"), common.secret("kc_agent_client_secret"),
                  common.secret("kc_admin_password")])
    print("versions:", J({p: md.version(p) for p in ("fastapi", "uvicorn", "httpx", "PyJWT", "langgraph", "cryptography")}),
          "python", sys.version.split()[0])
    print("keycloak.acme.local resolves on host?", end=" ")
    import socket
    try:
        socket.gethostbyname("keycloak.acme.local"); print("yes")
    except OSError:
        print("no -> HostRewrite transport (Host header giu nguyen)")

    snap = kc("snapshot")
    snap_file = HERE / "kc_snapshot_before.json"
    if "8310" in snap or "spike-b-" in json.loads(snap).get("spike_b_clients", ""):
        print("CANH BAO: Keycloak dang o trang thai do lan chay truoc; giu nguyen kc_snapshot_before.json cu")
    else:
        snap_file.write_text(snap, encoding="utf8")
    print("== kc_setup setup ==")
    print(kc("setup", {"SPIKE_B_PW_AN": pw_an, "SPIKE_B_PW_BINH": pw_binh}).strip())

    start(signer.app, SIGNER_PORT); start(agent.app, AGENT_PORT); start(bff.app, BFF_PORT)
    agent.SIGNER_JWKS = f"http://127.0.0.1:{SIGNER_PORT}/v1/jwks"
    bff.AGENT_URL = f"http://127.0.0.1:{AGENT_PORT}"; bff.SIGNER_URL = f"http://127.0.0.1:{SIGNER_PORT}"

    # ---------------- C1 ----------------
    an, binh = Browser(), Browser()
    cb = an.login("an.nguyen", pw_an)
    sess_an = an.session()
    lc = common.claims_unverified(sess_an["tokens"]["login"])
    print("  login token claims:", J({**common.show_claims(lc), "iss": lc.get("iss"), "has_sid": "sid" in lc}))
    sc = [f"{k}: " + re.sub(r"=[^;]+", "=<sid-value-redacted>", v, count=1) for k, v in cb.headers.multi_items() if k.lower() == "set-cookie"]
    print("  callback status", cb.status_code, "location", cb.headers.get("location"), "Set-Cookie:", sc)
    ck_ok = any("httponly" in s.lower() and "samesite=strict" in s.lower() for s in sc)
    rec("C1", "login qua BFF (code+PKCE S256, scope=openid), aud login token",
        bff.common.aud_list(lc) == ["chat-ui"] and ck_ok,
        f"aud={lc.get('aud')} azp={lc.get('azp')} cookie HttpOnly+SameSite=Strict={ck_ok}")
    me = an.c.get(f"{BFF_BASE}/api/me").json()
    print("  /api/me keys:", sorted(me))
    scan_browser([an], "C1-scan")

    # ---------------- C2 ----------------
    ta = bff.get_token(sess_an, "agent"); tb = bff.get_token(sess_an, "signer")
    for code, name, t, want in (("C2a", "exchange audience=agent-service scope=agent:invoke", ta, "agent-service"),
                                ("C2b", "exchange audience=approval-signer scope=signer:approve", tb, "approval-signer")):
        c = common.claims_unverified(t)
        print(f"  {code} claims:", J(common.show_claims(c)))
        rec(code, name, want in common.aud_list(c) and c.get("sub") == lc["sub"],
            f"azp thuc te={c.get('azp')} aud={c.get('aud')} chat-ui_in_aud={'chat-ui' in common.aud_list(c)} act={'act' in c}")
    cs = bff.client_secret()
    st, body = common.exchange("chat-ui", cs, sess_an["tokens"]["login"], audience="approval-signer")
    rec("C2c", "exchange audience=approval-signer KHONG scope (tham khao)", None, claims_or_err(st, body))
    st, body = common.exchange("chat-ui", cs, sess_an["tokens"]["login"], audience=["agent-service", "approval-signer"],
                               scope="agent:invoke signer:approve")
    rec("C2d", "exchange gop 2 audience + 2 scope (tham khao)", None, claims_or_err(st, body))

    # C2e
    print("== C2e: kc_setup export ==")
    exp = kc("export")
    pre, _, rest = exp.partition("== PARTIAL-EXPORT-BEGIN ==")
    print(pre.strip())
    pj = json.loads(rest.partition("== PARTIAL-EXPORT-END ==")[0])
    print("  partial-export attributes:", J({c["clientId"]: c.get("attributes") for c in pj["clients"] if c["clientId"] in ("chat-ui", "agent-service")}))
    d = Path(tempfile.mkdtemp(prefix="kcjar_"))
    jar_name = subprocess.run(["docker", "compose", "exec", "-T", "keycloak", "bash", "-c", "ls /opt/keycloak/lib/lib/main/*admin-ui*.jar"],
                              cwd=REPO, capture_output=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"}).stdout.decode().split()
    found = {}
    for jn in jar_name:
        if "rest-admin-ui-ext" in jn:
            continue
        dest = d / "admin-ui.jar"
        subprocess.run(["docker", "compose", "cp", f"keycloak:{jn}", str(dest)], cwd=REPO, capture_output=True,
                       env={**os.environ, "MSYS_NO_PATHCONV": "1"})
        rx = re.compile(rb"[A-Za-z0-9_.\-]*token[._-]?exchange[A-Za-z0-9_.\-]*", re.I)
        with zipfile.ZipFile(dest) as z:
            for n in z.namelist():
                if n.endswith((".js", ".json", ".html")):
                    for m in rx.findall(z.read(n)):
                        found[m.decode()] = found.get(m.decode(), 0) + 1
    print("  grep token.exchange trong admin-ui jar (khong co unzip trong container -> docker cp + python zipfile tren host):")
    for k, v in sorted(found.items(), key=lambda x: -x[1])[:15]:
        print("   ", k, "x", v)
    probe_ok = probe_attr(an)
    rec("C2e", "ten attribute that duoc server ton trong (probe spike-b-probe)", probe_ok,
        "xem '== probe-attr ==' o tren")

    # ---------------- C3 ----------------
    intent_an = {"intent_id": pysecrets.token_hex(8), "sub": lc["sub"], "op": "tickets.close", "target": "TCK-1001",
                 "args": {"resolution": "fixed"}, "exp": int(time.time()) + 600}
    r = signer_call(tb, intent_an)
    rec("C3i", "signer: token (b) cua an + intent sub=an", r.status_code == 200 and "approval_jws" in r.json(), f"HTTP {r.status_code}")
    r = signer_call(ta, intent_an)
    rec("C3ii", "signer: token (a) aud=agent-service", r.status_code in (401, 403), f"HTTP {r.status_code} {r.text[:120]}")
    r = signer_call(sess_an["tokens"]["login"], intent_an)
    rec("C3iii", "signer: token dang nhap aud=chat-ui", r.status_code in (401, 403), f"HTTP {r.status_code} {r.text[:120]}")
    binh.login("binh.tran", pw_binh)
    tb_binh = bff.get_token(binh.session(), "signer")
    r = signer_call(tb_binh, intent_an)
    rec("C3iv", "signer: binh.tran (token b cua binh) ky intent cua an", r.status_code == 403, f"HTTP {r.status_code} {r.text[:120]}")

    # ---------------- C5 ----------------
    def new_thread(msg):
        r = an.api("POST", "/api/chat", {"message": msg})
        return r, r.json()

    r, d1 = new_thread("dong ticket TCK-1001")
    rec("C5a-1", "POST /api/chat -> interrupt payload", r.status_code == 200 and d1.get("status") == "interrupted",
        f"HTTP {r.status_code} intent={J(d1.get('intent'))}")
    r = an.api("POST", "/api/approvals", {"thread_id": d1["thread_id"], "intent_id": d1["intent"]["intent_id"], "decision": "approve"})
    rec("C5a", "approve -> executed", r.status_code == 200 and r.json().get("status") == "executed", f"HTTP {r.status_code} {r.text}")
    r, d2 = new_thread("dong ticket TCK-1001 (reject)")
    r = an.api("POST", "/api/approvals", {"thread_id": d2["thread_id"], "intent_id": d2["intent"]["intent_id"], "decision": "reject"})
    rec("C5b", "reject -> rejected (khong thuc thi)", r.status_code == 200 and r.json().get("status") == "rejected", f"HTTP {r.status_code} {r.text}")
    # C5c
    r, d3 = new_thread("c5c")
    it3 = d3["intent"]
    jws = signer_call(tb, it3, "reject").json()["approval_jws"]
    r = agent_call(ta, f"/v1/runs/{d3['thread_id']}/resume", {"approval_jws": tamper_decision(jws, "approve")})
    rec("C5c", "resume truc tiep bang JWS bi sua (reject->approve, giu chu ky)", r.status_code == 200 and r.json().get("status") == "refused",
        f"HTTP {r.status_code} {r.text}")
    # C5d
    r, d4 = new_thread("c5d")
    other = {**d4["intent"], "args": {"resolution": "wontfix", "note": "intent khac"}}
    jws2 = signer_call(tb, other, "approve").json()["approval_jws"]
    r = agent_call(ta, f"/v1/runs/{d4['thread_id']}/resume", {"approval_jws": jws2})
    rec("C5d", "resume bang JWS hop le cua intent KHAC (hash lech)", r.status_code == 200 and r.json().get("status") == "refused",
        f"HTTP {r.status_code} {r.text}")
    # C5e
    r, d5 = new_thread("c5e")
    r = an.c.post(f"{BFF_BASE}/api/approvals", json={"thread_id": d5["thread_id"], "intent_id": d5["intent"]["intent_id"], "decision": "approve"})
    rec("C5e", "POST /api/approvals thieu X-CSRF-Token", r.status_code == 403, f"HTTP {r.status_code}")
    rb = binh.c.get(f"{BFF_BASE}/api/me")  # tham khao: binh khong the dung thread cua an
    r = binh.api("POST", "/api/approvals", {"thread_id": d5["thread_id"], "intent_id": d5["intent"]["intent_id"], "decision": "approve"})
    rec("C5f", "(them) binh.tran approve thread cua an qua BFF cua binh", r.status_code in (403, 404), f"HTTP {r.status_code} {r.text}")

    # ---------------- C4 ----------------
    r, d6 = new_thread("c4 prep")
    held = agent.LAST_BEARER
    hc = common.claims_unverified(held)
    print("  token agent da nhan/luu:", J(common.show_claims(hc)), "== token (a) cua session:", held == sess_an["tokens"]["agent"])
    ags = common.secret("kc_agent_client_secret")
    for code, desc, kw in (("C4i", "agent-service exchange audience=approval-signer scope=signer:approve", dict(audience="approval-signer", scope="signer:approve")),
                           ("C4ii", "agent-service exchange audience=approval-signer (khong scope)", dict(audience="approval-signer")),
                           ("C4iii", "agent-service exchange scope=signer:approve (khong audience)", dict(scope="signer:approve"))):
        st, body = common.exchange("agent-service", ags, held, **kw)
        if st == 200:
            t = body["access_token"]; r = signer_call(t, intent_an)
            rec(code, desc, False, "PHAT HIEN: " + claims_or_err(st, body) + f" | goi signer -> HTTP {r.status_code} {r.text[:100]}")
        else:
            rec(code, desc, True, "tu choi: " + claims_or_err(st, body))
    st, body = common.exchange("agent-service", ags, held, audience="llm-gateway", scope="llm:invoke")
    rec("C4c", "doi chung: agent-service exchange audience=llm-gateway scope=llm:invoke", st == 200, claims_or_err(st, body))
    if st == 200:
        r = signer_call(body["access_token"], intent_an)
        print("  token llm-gateway goi signer ->", r.status_code, r.text[:100])

    scan_browser([an, binh], "C1b")


def probe_attr(an):
    print("== probe-attr ==")
    sec = kc("probe-create").strip().splitlines()[-1]
    SCRUB.append(sec)
    try:
        st, ccb = None, None
        r = httpx.post(common.TOKEN_URL, data={"grant_type": "client_credentials", "client_id": "spike-b-probe", "client_secret": sec})
        own = r.json().get("access_token")
        subj = {"chat-ui login token": an.session()["tokens"]["login"], "probe own client_credentials token": own}
        res = {}
        for phase in ("before", "after"):
            if phase == "after":
                print("  kc_setup probe-enable:", kc("probe-enable").strip().splitlines()[-1])
            for name, t in subj.items():
                if not t:
                    continue
                st, body = common.exchange("spike-b-probe", sec, t, audience="agent-service")
                res[(phase, name)] = (st, err_of(body))
                print(f"  {phase} enable: subject={name} audience=agent-service -> HTTP {st} {err_of(body)}"
                      + (" claims=" + J(common.show_claims(common.claims_unverified(body['access_token']))) if st == 200 else ""))
        return any(res[("before", n)] != res[("after", n)] for n in subj if ("before", n) in res)
    finally:
        print("  kc_setup probe-delete:", kc("probe-delete", check=False).strip().splitlines()[-1:])


if __name__ == "__main__":
    sys.stdout = Tee(HERE / "output.txt")
    no_cleanup = "--no-cleanup" in sys.argv
    try:
        run()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stdout)
        RESULTS.append(("EXC", "FAIL"))
    finally:
        if not no_cleanup:
            print("== kc_setup cleanup ==")
            try:
                print(kc("cleanup", check=False).strip())
            except Exception as e:
                print("CLEANUP LOI:", e)
        else:
            print("== --no-cleanup: KHONG don Keycloak ==")
        print("SUMMARY")
        for c, t in RESULTS:
            print(f"  {c}: {t}")
        bad = [c for c, t in RESULTS if t == "FAIL"]
        print("ALL PASS" if not bad else f"FAIL: {bad}")
        sys.stdout.flush()
