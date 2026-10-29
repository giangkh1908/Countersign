"""Spike C: chay toan bo ca A-F. Yeu cau env: SPIKE_C_PW, SPIKE_C_SECRET (do run.sh sinh).

Khoi dong resource_servers.py (tickets :8931, gateway :8932) bang subprocess va tat khi xong.
Khong bao gio in token tho: chi in claims da decode.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from broker import (CachingTokenBroker, ClientCredentialsWithUserTokenBroker,  # noqa: E402
                    KeycloakTokenExchangeBroker, TokenExchangeError, decode_unverified)

HERE = Path(__file__).parent
TOKEN_URL = "http://localhost:8080/realms/acme/protocol/openid-connect/token"
TICKETS = "http://127.0.0.1:8931"
GATEWAY = "http://127.0.0.1:8932"
PW, LOGIN_SECRET = os.environ["SPIKE_C_PW"], os.environ["SPIKE_C_SECRET"]
AGENT_SECRET = (HERE.parent.parent / "secrets" / "kc_agent_client_secret").read_text().strip()
GW_KEY = secrets.token_hex(16)
GRANT_X = "urn:ietf:params:oauth:grant-type:token-exchange"
TYPE_AT = "urn:ietf:params:oauth:token-type:access_token"

RESULTS: list[tuple[str, bool]] = []


def short(tok: str) -> str:
    return f"{tok[:3]}...(len={len(tok)})"


def check(name: str, ok: bool, extra: str = ""):
    RESULTS.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}".rstrip())


def info(msg: str):
    print(f"[INFO] {msg}")


def section(t: str):
    print(f"\n{'=' * 8} {t} {'=' * 8}")


def view(c: dict) -> dict:
    d = {k: c.get(k) for k in ("aud", "azp", "scope", "sub", "dept", "clearance", "typ", "sid")}
    d["exp-iat"] = c["exp"] - c["iat"]
    d["act"] = c.get("act", "<none>")
    return d


def tamper(tok: str, **changes) -> str:
    h, p, s = tok.split(".")
    d = decode_unverified(tok)
    d.update(changes)
    p2 = base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{h}.{p2}.{s}"


def garbage_sig(tok: str) -> str:
    h, p, _ = tok.split(".")
    return f"{h}.{p}.{base64.urlsafe_b64encode(os.urandom(256)).rstrip(b'=').decode()}"


def stats(name: str, xs: list[float]):
    xs = sorted(xs)
    p95 = xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]
    print(f"[LAT] {name}: n={len(xs)} p50={statistics.median(xs):.1f}ms p95={p95:.1f}ms "
          f"min={xs[0]:.1f}ms max={xs[-1]:.1f}ms")


# ------------------------------------------------------------------ Keycloak raw calls
async def login(http, client: str, user: str) -> str:
    r = await http.post(TOKEN_URL, data=dict(grant_type="password", client_id=client, client_secret=LOGIN_SECRET,
                                             username=user, password=PW))
    r.raise_for_status()
    return r.json()["access_token"]


async def raw_exchange(http, subject: str, *, client="agent-service", secret=None, audience=None, scope=None,
                       extra: dict | None = None, client_id_override=None):
    data = {"grant_type": GRANT_X, "client_id": client_id_override or client,
            "client_secret": AGENT_SECRET if secret is None and client == "agent-service" else (secret or LOGIN_SECRET),
            "subject_token": subject, "subject_token_type": TYPE_AT, "requested_token_type": TYPE_AT}
    if audience:
        data["audience"] = audience
    if scope:
        data["scope"] = scope
    data.update(extra or {})
    r = await http.post(TOKEN_URL, data=data)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:200]}


def describe(status: int, body: dict) -> str:
    if status != 200:
        return f"HTTP {status} error={body.get('error')!r} error_description={body.get('error_description')!r}"
    c = decode_unverified(body["access_token"])
    return (f"HTTP 200 token={short(body['access_token'])} aud={c.get('aud')} azp={c.get('azp')} "
            f"scope={c.get('scope')!r} expires_in={body.get('expires_in')} refresh={'refresh_token' in body}")


async def user_subject(http, user: str, client="spike-c-login"):
    lt = await login(http, client, user)
    st, body = await raw_exchange(http, lt, client=client, secret=LOGIN_SECRET,
                                  audience="agent-service", scope="agent:invoke")
    assert st == 200, body
    return lt, body["access_token"]


# ------------------------------------------------------------------ MCP over HTTP
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _parse(r: httpx.Response) -> dict:
    t = r.text
    if "data:" in t and r.headers.get("content-type", "").startswith("text/event-stream"):
        for line in t.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
    return json.loads(t)


async def mcp_whoami(http, path: str, bearer: str | None, extra: dict | None = None):
    h = dict(HDR)
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    h.update(extra or {})
    r = await http.post(TICKETS + path, headers=h, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}})
    if r.status_code != 200:
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:120]}
    m = _parse(r)
    res = m.get("result", {})
    ident = res.get("structuredContent") or json.loads(res["content"][0]["text"])
    return 200, ident


async def gw_whoami(http, path: str, key: str | None, user_token: str | None):
    h = {}
    if key:
        h["Authorization"] = f"Bearer {key}"
    if user_token:
        h["X-Acme-User-Token"] = user_token
    r = await http.post(GATEWAY + path, headers=h, json={})
    return r.status_code, r.json()


def expect_401(name, res, reason=None):
    st, body = res
    ok = st == 401 and (reason is None or body.get("reason") == reason)
    check(name, ok, f"-> HTTP {st} reason={body.get('reason')!r} detail={body.get('detail')!r}")


async def wait_port(port: int):
    async with httpx.AsyncClient() as h:
        for _ in range(80):
            try:
                await h.get(f"http://127.0.0.1:{port}/health")
                return
            except Exception:
                await asyncio.sleep(0.25)
    raise RuntimeError(f"port {port} khong len")


# ------------------------------------------------------------------ main
async def main():
    env = {**os.environ, "SPIKE_C_GW_KEY": GW_KEY, "PYTHONUNBUFFERED": "1"}
    procs = [subprocess.Popen([sys.executable, str(HERE / "resource_servers.py"), w], env=env)
             for w in ("tickets", "gateway")]
    try:
        await asyncio.gather(wait_port(8931), wait_port(8932))
        await cases()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)
    section("TOM TAT")
    bad = [n for n, ok in RESULTS if not ok]
    print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS")
    for n in bad:
        print(f"  FAIL: {n}")
    sys.exit(1 if bad else 0)


async def cases():
    http = httpx.AsyncClient(timeout=15)
    broker = KeycloakTokenExchangeBroker(TOKEN_URL, "agent-service", AGENT_SECRET, http)

    # subject token ngan han (15s) tao som de dung cho ca het han
    short_login = await login(http, "spike-c-short", "chi.le")
    st, b = await raw_exchange(http, short_login, client="spike-c-short", secret=LOGIN_SECRET,
                               audience="agent-service", scope="agent:invoke")
    short_subject = b["access_token"]
    sc = decode_unverified(short_subject)
    st2, b2 = await raw_exchange(http, short_subject, audience="tickets-mcp", scope="tickets:read")
    short_t_c = decode_unverified(b2["access_token"]) if st2 == 200 else {}  # chi de do lifespan cua token exchange
    # token aud=tickets-mcp song 15s lay bang direct grant tren spike-c-short (scope tickets:read lien ket san)
    rr = await http.post(TOKEN_URL, data=dict(grant_type="password", client_id="spike-c-short", client_secret=LOGIN_SECRET,
                                              username="chi.le", password=PW, scope="tickets:read"))
    short_tickets = rr.json()["access_token"]
    st_c = decode_unverified(short_tickets)
    short_t0 = time.time()

    users = {}
    for u in ("chi.le", "tam.vu"):
        users[u] = await user_subject(http, u)
    login_tok, subject = users["chi.le"]
    lc, scl = decode_unverified(login_tok), decode_unverified(subject)

    section("A. POSITIVE - agent-service exchange (RFC 8693, Keycloak std token exchange V2)")
    info(f"login token (aud=spike-c-login, vai tro token chat-ui): {view(lc)}")
    info(f"subject token (aud=agent-service, vai tro token BFF gui agent): {view(scl)}")
    info("subject exchange spike-c-login->agent-service: dung scope agent:invoke (lien ket san scope co san, KHONG sua scope)")

    async def positive(user, lt, st_, audience, scopes):
        t = await broker.token_for(st_, audience, frozenset(scopes))
        c = decode_unverified(t.value)
        sc_ = decode_unverified(st_)
        lc_ = decode_unverified(lt)
        label = f"{user} {audience} {sorted(scopes)}"
        info(f"{label}: {view(c)} exp-vs-subject-exp={c['exp'] - sc_['exp']}s meta={t.meta}")
        check(f"A {label}: aud chua {audience}", audience in ([c['aud']] if isinstance(c['aud'], str) else c['aud']))
        check(f"A {label}: scope == yeu cau", set(c["scope"].split()) - {"acme-claims"} == set(scopes),
              f"(scope={c['scope']!r})")
        for k in ("sub", "dept", "clearance"):
            check(f"A {label}: {k} giu nguyen (subject & login)", c.get(k) == sc_.get(k) == lc_.get(k),
                  f"({k}={c.get(k)!r})")
        check(f"A {label}: azp == agent-service", c.get("azp") == "agent-service", f"(azp={c.get('azp')})")
        check(f"A {label}: khong co act", "act" not in c)
        return t

    for tgt in (("tickets-mcp", ["tickets:read"]), ("tickets-mcp", ["tickets:write"]),
                ("tickets-mcp", ["tickets:read", "tickets:write"]), ("llm-gateway", ["llm:invoke"])):
        try:
            await positive("chi.le", login_tok, subject, *tgt)
        except TokenExchangeError as e:
            check(f"A chi.le {tgt}", False, f"-> {e}")
    tl, ts = users["tam.vu"]
    for tgt in (("tickets-mcp", ["tickets:read"]), ("llm-gateway", ["llm:invoke"])):
        try:
            await positive("tam.vu", tl, ts, *tgt)
        except TokenExchangeError as e:
            check(f"A tam.vu {tgt}", False, f"-> {e}")

    section("B. THAM DO (ghi nguyen hanh vi)")
    probes = [
        ("audience=tickets-mcp, KHONG scope", dict(audience="tickets-mcp")),
        ("scope=tickets:read, KHONG audience", dict(scope="tickets:read")),
        ("audience=tickets-mcp + scope=llm:invoke (lech)", dict(audience="tickets-mcp", scope="llm:invoke")),
        ("MOT audience=tickets-mcp + scope tickets:read llm:invoke",
         dict(extra=None, audience="tickets-mcp", scope="tickets:read llm:invoke")),
        ("audience=llm-gateway, KHONG scope", dict(audience="llm-gateway")),
    ]
    for label, kw in probes:
        st, body = await raw_exchange(http, subject, **kw)
        info(f"B {label}: {describe(st, body)}")
    # hai audience: tham so audience lap 2 lan
    from urllib.parse import urlencode
    r = await http.post(TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"}, content=urlencode([
        ("grant_type", GRANT_X), ("client_id", "agent-service"), ("client_secret", AGENT_SECRET),
        ("subject_token", subject), ("subject_token_type", TYPE_AT),
        ("audience", "tickets-mcp"), ("audience", "llm-gateway"), ("scope", "tickets:read llm:invoke")]))
    info(f"B hai tham so audience lap lai + 2 scope: {describe(r.status_code, r.json())}")

    section("C. CA AM")
    for sc_name in ("agent:invoke", "analytics:write", "admin"):
        st, body = await raw_exchange(http, subject, audience="tickets-mcp", scope=sc_name)
        if st == 200:
            c = decode_unverified(body["access_token"])
            ok = sc_name not in c.get("scope", "").split()
            check(f"C1 scope {sc_name!r} khong gan cho agent-service", ok, f"-> {describe(st, body)}")
        else:
            check(f"C1 scope {sc_name!r} khong gan cho agent-service", True, f"-> {describe(st, body)}")
    # ket hop scope hop le + scope khong duoc gan
    st, body = await raw_exchange(http, subject, audience="tickets-mcp", scope="tickets:read agent:invoke")
    info(f"C1b scope 'tickets:read agent:invoke': {describe(st, body)}")
    st, body = await raw_exchange(http, login_tok, audience="tickets-mcp", scope="tickets:read")
    check("C2 subject token aud=spike-c-login (khong chua agent-service) bi tu choi", st != 200,
          f"-> {describe(st, body)}")
    st, body = await raw_exchange(http, tamper(subject, sub="evil-sub", dept=["FINANCE"]),
                                  audience="tickets-mcp", scope="tickets:read")
    check("C4a subject bi sua payload (sub/dept) bi tu choi", st != 200, f"-> {describe(st, body)}")
    st, body = await raw_exchange(http, garbage_sig(subject), audience="tickets-mcp", scope="tickets:read")
    check("C4b subject chu ky rac bi tu choi", st != 200, f"-> {describe(st, body)}")
    st, body = await raw_exchange(http, subject, secret="wrong-secret-" + secrets.token_hex(4),
                                  audience="tickets-mcp", scope="tickets:read")
    check("C5 client secret agent-service sai bi tu choi", st == 401, f"-> {describe(st, body)}")

    # cho subject ngan han het han
    info(f"short subject: exp-iat={sc['exp'] - sc['iat']}s (client spike-c-short access.token.lifespan=15); "
         f"token tickets doi tu no: exp-iat={(short_t_c.get('exp', 0) - short_t_c.get('iat', 0))}s "
         f"exp-vs-subject-exp={short_t_c.get('exp', 0) - sc['exp']}s")
    info(f"token direct-grant spike-c-short aud={st_c['aud']} scope={st_c['scope']!r} exp-iat={st_c['exp'] - st_c['iat']}s (dung cho ca het han o resource server)")
    wait = max(sc["exp"], st_c["exp"]) + 2 - time.time()
    if wait > 0 and wait < 330:
        info(f"cho {wait:.0f}s cho token ngan han het han ...")
        await asyncio.sleep(wait)
    expired_subject = short_subject
    st, body = await raw_exchange(http, expired_subject, audience="tickets-mcp", scope="tickets:read")
    check("C3 subject token het han bi tu choi", st != 200, f"-> {describe(st, body)}")

    section("D. RESOURCE SERVERS")
    # Dung lai exchange token tickets/llm moi
    tk = await broker.token_for(subject, "tickets-mcp", frozenset({"tickets:read"}))
    lk = await broker.token_for(subject, "llm-gateway", frozenset({"llm:invoke"}))
    tk_tam = await broker.token_for(ts, "tickets-mcp", frozenset({"tickets:read"}))
    for who, tok, base in (("chi.le", tk, scl), ("tam.vu", tk_tam, decode_unverified(ts))):
        st, idn = await mcp_whoami(http, "/mcp", tok.value)
        info(f"D tickets-mcp /mcp whoami ({who}): HTTP {st} {idn}")
        check(f"D tickets /mcp chap nhan token exchange, whoami == {who}",
              st == 200 and idn["sub"] == base["sub"] and idn["dept"] == base["dept"]
              and idn["clearance"] == base["clearance"] and idn["azp"] == "agent-service")
    expect_401("D tickets /mcp tu choi token aud=agent-service goc", await mcp_whoami(http, "/mcp", subject), "audience")
    expect_401("D tickets /mcp tu choi token llm-gateway (nham dich)", await mcp_whoami(http, "/mcp", lk.value), "audience")
    expect_401("D tickets /mcp tu choi token bi sua", await mcp_whoami(http, "/mcp", tamper(tk.value, sub="evil")), "signature")
    expect_401("D tickets /mcp tu choi token chu ky rac", await mcp_whoami(http, "/mcp", garbage_sig(tk.value)), "signature")
    expect_401("D tickets /mcp tu choi khong token", await mcp_whoami(http, "/mcp", None), "missing_bearer")
    tw = await broker.token_for(subject, "tickets-mcp", frozenset({"tickets:write"}))
    expect_401("D tickets /mcp tu choi token chi co tickets:write (thieu tickets:read)",
               await mcp_whoami(http, "/mcp", tw.value), "scope")
    if time.time() > st_c["exp"]:
        expect_401("D tickets /mcp tu choi token aud=tickets-mcp scope tickets:read het han (direct grant 15s)",
                   await mcp_whoami(http, "/mcp", short_tickets), "expired")
    else:
        expect_401("D tickets /mcp tu choi token (aud=agent-service) het han",
                   await mcp_whoami(http, "/mcp", expired_subject))
    # gateway
    st, idn = await gw_whoami(http, "/v1/whoami", GW_KEY, lk.value)
    info(f"D gateway /v1/whoami: HTTP {st} {idn}")
    check("D gateway chap nhan token llm-gateway, danh tinh == chi.le",
          st == 200 and idn["sub"] == scl["sub"] and idn["dept"] == scl["dept"] and idn["clearance"] == scl["clearance"])
    expect_401("D gateway tu choi token aud=agent-service goc", await gw_whoami(http, "/v1/whoami", GW_KEY, subject), "audience")
    expect_401("D gateway tu choi token tickets-mcp", await gw_whoami(http, "/v1/whoami", GW_KEY, tk.value), "audience")
    expect_401("D gateway tu choi API key sai", await gw_whoami(http, "/v1/whoami", "wrong", lk.value), "api_key")
    expect_401("D gateway tu choi token llm bi sua", await gw_whoami(http, "/v1/whoami", GW_KEY, tamper(lk.value, sub="evil")), "signature")

    section("F. PHUONG AN B (client_credentials + X-Acme-User-Token)")
    bbroker = ClientCredentialsWithUserTokenBroker(TOKEN_URL, "agent-service", AGENT_SECRET, http)
    cc = await bbroker.token_for(subject, "tickets-mcp", frozenset({"tickets:read"}))
    ccc = decode_unverified(cc.value)
    info(f"F cc-token claims: {{'aud': {ccc.get('aud')}, 'azp': {ccc.get('azp')}, 'sub': {ccc.get('sub')}, "
         f"'scope': {ccc.get('scope')!r}, 'dept': {ccc.get('dept')}, 'clearance': {ccc.get('clearance')}, "
         f"'exp-iat': {ccc['exp'] - ccc['iat']}, 'username': {ccc.get('preferred_username')}}} meta={cc.meta}")
    check("F cc-token sub KHAC sub user (la service account)", ccc["sub"] != scl["sub"])
    B = lambda ut: {"X-Acme-User-Token": ut} if ut else {}  # noqa: E731
    st, idn = await mcp_whoami(http, "/mcp-b", cc.value, B(subject))
    info(f"F /mcp-b whoami: HTTP {st} {idn}")
    check("F /mcp-b: cc-token + header user token -> danh tinh chi.le",
          st == 200 and idn["sub"] == scl["sub"] and idn["dept"] == scl["dept"] and idn["clearance"] == scl["clearance"])
    expect_401("F /mcp-b thieu header", await mcp_whoami(http, "/mcp-b", cc.value), "missing_user_token")
    expect_401("F /mcp-b header la token aud=spike-c-login", await mcp_whoami(http, "/mcp-b", cc.value, B(login_tok)), "audience")
    expect_401("F /mcp-b header het han", await mcp_whoami(http, "/mcp-b", cc.value, B(expired_subject)), "expired")
    expect_401("F /mcp-b header bi sua", await mcp_whoami(http, "/mcp-b", cc.value, B(tamper(subject, sub="evil"))), "signature")
    expect_401("F /mcp-b Bearer la token user thay vi cc", await mcp_whoami(http, "/mcp-b", subject, B(subject)))
    # rui ro
    section("F2. RUI RO PHUONG AN B")
    st, idn = await gw_whoami(http, "/v1-b/whoami", GW_KEY, subject)
    info(f"F2 gateway-B /v1-b/whoami voi cung user token aud=agent-service: HTTP {st} {idn}")
    check("F2 (rui ro) cung user token aud=agent-service duoc CA /mcp-b VA /v1-b/whoami chap nhan (replay lien dich vu)",
          st == 200 and idn["sub"] == scl["sub"])
    st1, i1 = await mcp_whoami(http, "/mcp-b", cc.value, B(subject))
    st2, i2 = await mcp_whoami(http, "/mcp-b", cc.value, B(ts))
    info(f"F2 cung cc-token, doi header: {i1.get('sub')} / {i2.get('sub')}")
    check("F2 (rui ro) cung credentials agent-service + bat ky user token aud=agent-service -> danh tinh user bat ky",
          st1 == st2 == 200 and i1["sub"] != i2["sub"])
    expect_401("F2 phuong an chinh: token tickets-mcp khong dung duoc o gateway /v1", await gw_whoami(http, "/v1/whoami", GW_KEY, tk.value), "audience")
    expect_401("F2 phuong an chinh: token tickets-mcp khong dung duoc o gateway-B /v1-b", await gw_whoami(http, "/v1-b/whoami", GW_KEY, tk.value), "audience")
    expect_401("F2 phuong an chinh: token tickets-mcp khong dung duoc lam header o /mcp-b", await mcp_whoami(http, "/mcp-b", cc.value, B(tk.value)), "audience")

    section("E. LATENCY (ms)")
    N = 20
    SUB = frozenset({"tickets:read"})
    LLM = frozenset({"llm:invoke"})

    async def timed(coro_fn, n=N):
        out = []
        for _ in range(n):
            t0 = time.perf_counter()
            await coro_fn()
            out.append((time.perf_counter() - t0) * 1000)
        return out

    for aud, scopes in (("tickets-mcp", SUB), ("llm-gateway", LLM)):
        await broker.token_for(subject, aud, scopes)  # warm-up (khong tinh)
        stats(f"exchange {aud} - httpx client dung lai (keep-alive)",
              await timed(lambda: broker.token_for(subject, aud, scopes)))

        async def fresh():
            async with httpx.AsyncClient(timeout=15) as h:
                await KeycloakTokenExchangeBroker(TOKEN_URL, "agent-service", AGENT_SECRET, h).token_for(subject, aud, scopes)
        stats(f"exchange {aud} - client moi moi lan", await timed(fresh))
    # So sanh: URL 127.0.0.1 (tranh tre ~40ms do localhost/dual-stack + delayed-ACK tren Windows)
    ip_url = TOKEN_URL.replace("localhost", "127.0.0.1")
    ip_broker = KeycloakTokenExchangeBroker(ip_url, "agent-service", AGENT_SECRET, httpx.AsyncClient(timeout=15))
    for aud, scopes in (("tickets-mcp", SUB), ("llm-gateway", LLM)):
        await ip_broker.token_for(subject, aud, scopes)
        stats(f"exchange {aud} - keep-alive, URL 127.0.0.1", await timed(lambda: ip_broker.token_for(subject, aud, scopes)))
    ip_cc = ClientCredentialsWithUserTokenBroker(ip_url, "agent-service", AGENT_SECRET, httpx.AsyncClient(timeout=15))
    stats("client_credentials (B) - keep-alive, URL 127.0.0.1", await timed(lambda: ip_cc.token_for(subject, "tickets-mcp", SUB)))
    stats("client_credentials (phuong an B) - client dung lai",
          await timed(lambda: bbroker.token_for(subject, "tickets-mcp", SUB)))
    cached = CachingTokenBroker(broker)
    stats("CachingTokenBroker 1 miss + 19 hit", await timed(lambda: cached.token_for(subject, "tickets-mcp", SUB)))
    info(f"cache hits={cached.hits} misses={cached.misses}")
    check("E cache: 1 miss + 19 hit", (cached.misses, cached.hits) == (1, 19))
    # cache khong luu tickets:write
    cw = CachingTokenBroker(broker)
    a = await cw.token_for(subject, "tickets-mcp", frozenset({"tickets:write"}))
    b = await cw.token_for(subject, "tickets-mcp", frozenset({"tickets:write"}))
    check("E cache khong cache scope tickets:write (2 token khac nhau)", a.value != b.value and cw.hits == 0)
    # cache tach theo user
    cu = CachingTokenBroker(broker)
    x = await cu.token_for(subject, "tickets-mcp", SUB)
    y = await cu.token_for(ts, "tickets-mcp", SUB)
    check("E cache khoa theo sub: 2 user -> 2 token, sub khac", x.sub != y.sub and cu.misses == 2)

    # verify JWT o resource server (PyJWT + JWKS cache)
    import resource_servers as rs
    rs._jwks.get_signing_keys()
    ts_ = []
    for _ in range(200):
        t0 = time.perf_counter()
        rs.verify(tk.value, audience="tickets-mcp", scope="tickets:read")
        ts_.append((time.perf_counter() - t0) * 1000)
    stats("verify JWT RS256 tai resource server (JWKS da cache)", ts_[:])
    # HTTP round-trip toi tickets /mcp (verify + MCP tool call)
    stats("tickets /mcp whoami end-to-end (HTTP, verify, tool)", await timed(lambda: mcp_whoami(http, "/mcp", tk.value)))
    await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
