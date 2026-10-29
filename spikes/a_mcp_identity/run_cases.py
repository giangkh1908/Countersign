"""Lay token that tu Keycloak, goi MCP server qua HTTP + FastMCP client, in 4 ca."""
import asyncio, base64, json, os, sys, time
import httpx
from fastmcp import Client
from fastmcp.client.auth import BearerAuth

KC = "http://localhost:8080/realms/acme/protocol/openid-connect/token"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8911/mcp"
PW = os.environ["SPIKE_A_PASSWORD"]  # mật khẩu đặt cho user test ở bước 1 (không commit)


def token(client, scope=None, user="an.nguyen"):
    d = dict(client_id=client, grant_type="password", username=user, password=PW)
    if scope: d["scope"] = scope
    r = httpx.post(KC, data=d); r.raise_for_status()
    return r.json()["access_token"]


def payload(t):
    p = t.split(".")[1]; return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def raw(label, tok):
    h = dict(HDR); 
    if tok: h["Authorization"] = f"Bearer {tok}"
    r = httpx.post(URL, json=INIT, headers=h)
    print(f"[{label}] HTTP {r.status_code} www-authenticate={r.headers.get('www-authenticate')!r} body={r.text[:120]!r}")
    return r.status_code


async def main():
    good = token("spike-a-cli", "openid docs:read")
    p = payload(good); print("good token claims:", {k: p.get(k) for k in ("sub", "iss", "aud", "azp", "dept", "clearance")})
    ok = True
    # (a)
    async with Client(URL, auth=BearerAuth(good)) as c:
        res = await c.call_tool("whoami", {})
        print("[a] tool whoami ->", res.data)
        ok &= res.data["sub"] == p["sub"] and res.data["dept"] == ["SALES"] and res.data["azp"] == "spike-a-cli"
    raw("a-raw", good) 
    # (b) aud sai: khong co docs:read -> aud thieu docs-mcp ; va aud=tickets-mcp
    nb = token("spike-a-cli", "openid"); print("   (b1) aud =", payload(nb).get("aud"))
    ok &= raw("b1 no-aud", nb) == 401
    tk = token("spike-a-cli", "openid tickets:read"); print("   (b2) aud =", payload(tk).get("aud"))
    ok &= raw("b2 aud=tickets-mcp", tk) == 401
    # (c)
    ok &= raw("c no token", None) == 401
    # (d1) het han
    short = token("spike-a-short"); print("   (d1) lifespan", payload(short)["exp"] - payload(short)["iat"], "s"); time.sleep(4)
    ok &= raw("d1 expired", short) == 401
    # (d2) chu ky sai: doi payload (sub) giu chu ky cu
    h, pl, s = good.split("."); d = json.loads(base64.urlsafe_b64decode(pl + "=" * (-len(pl) % 4))); d["sub"] = "evil"
    pl2 = base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    ok &= raw("d2 tampered payload", f"{h}.{pl2}.{s}") == 401
    # (d3) ky bang khoa RSA khac, claims hop le
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({**p, "exp": int(time.time()) + 300}, k, algorithm="RS256", headers={"kid": jwt.get_unverified_header(good)["kid"]})
    ok &= raw("d3 forged key same kid", forged) == 401
    # (d4) alg=none
    none = jwt.encode({**p, "exp": int(time.time()) + 300}, None, algorithm="none")
    ok &= raw("d4 alg=none", none) == 401
    print("ALL PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)

asyncio.run(main())
