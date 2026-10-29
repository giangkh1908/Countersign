"""BFF toi thieu cho client chat-ui: code+PKCE, session server-side, token exchange (RFC 8693)."""
import base64, hashlib, os, secrets, time
from urllib.parse import urlencode
import httpx, jwt
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
import common

PUBLIC_BASE = os.environ.get("SPIKE_B_BFF_URL", "http://localhost:8310")
AGENT_URL = os.environ.get("SPIKE_B_AGENT_URL", "http://127.0.0.1:8312")
SIGNER_URL = os.environ.get("SPIKE_B_SIGNER_URL", "http://127.0.0.1:8311")
CLIENT_ID = "chat-ui"
REDIRECT_URI = f"{PUBLIC_BASE}/auth/callback"
# __Host-sid bat buoc Secure; cookie jar cua httpx/http.cookiejar khong gui cookie Secure qua http,
# nen khi BFF chay http (localhost) dung "sid" khong Secure; khi https dung "__Host-sid" + Secure.
SECURE = PUBLIC_BASE.startswith("https://")
COOKIE = "__Host-sid" if SECURE else "sid"

# That: Redis "bff:sess:{sid}" (ma hoa); o day dict in-memory.
SESSIONS: dict = {}
PENDING: dict = {}   # state -> {verifier, nonce}

EXCHANGES = {"agent": ("agent-service", "agent:invoke"), "signer": ("approval-signer", "signer:approve")}

app = FastAPI()


def client_secret() -> str:
    return common.secret("bff_oidc_client_secret")


def get_token(sess: dict, kind: str) -> str:
    """Hai exchange RIENG (khong gop audience). Token giu server-side trong session."""
    if kind not in sess["tokens"]:
        aud, scope = EXCHANGES[kind]
        st, body = common.exchange(CLIENT_ID, client_secret(), sess["tokens"]["login"], audience=aud, scope=scope)
        if st != 200:
            raise HTTPException(502, f"exchange {kind} failed: {st} {body}")
        sess["tokens"][kind] = body["access_token"]
    return sess["tokens"][kind]


def session_of(req: Request) -> dict:
    s = SESSIONS.get(req.cookies.get(COOKIE, ""))
    if not s:
        raise HTTPException(401, "no session")
    return s


def csrf_ok(req: Request, sess: dict):
    if not secrets.compare_digest(req.headers.get("x-csrf-token", ""), sess["csrf"]):
        raise HTTPException(403, "csrf")


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


@app.get("/auth/login")
def login():
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    PENDING[state] = {"verifier": verifier, "nonce": nonce}
    q = urlencode({"client_id": CLIENT_ID, "response_type": "code", "scope": "openid", "redirect_uri": REDIRECT_URI,
                   "state": state, "nonce": nonce, "code_challenge": b64u(hashlib.sha256(verifier.encode()).digest()),
                   "code_challenge_method": "S256"})
    return RedirectResponse(f"{common.KC_PUBLIC}/protocol/openid-connect/auth?{q}", status_code=302)


@app.get("/auth/callback")
def callback(code: str = "", state: str = "", error: str = ""):
    pend = PENDING.pop(state, None)
    if error or not pend:
        raise HTTPException(400, f"bad callback error={error!r} state_known={bool(pend)}")
    r = httpx.post(common.TOKEN_URL, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI, "client_id": CLIENT_ID,
        "client_secret": client_secret(), "code_verifier": pend["verifier"]}, timeout=15)
    if r.status_code != 200:
        raise HTTPException(502, f"code exchange failed: {r.status_code} {r.text[:200]}")
    tok = r.json()
    claims = common.verify_kc_token(tok["access_token"])
    if CLIENT_ID not in common.aud_list(claims):
        raise HTTPException(401, "aud")
    idc = jwt.decode(tok["id_token"], common._jwks.get_signing_key_from_jwt(tok["id_token"]).key,
                     algorithms=["RS256"], audience=CLIENT_ID, issuer=common.ISSUER)
    if idc.get("nonce") != pend["nonce"]:
        raise HTTPException(400, "nonce")
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = {"sub": claims["sub"], "username": claims.get("preferred_username"), "csrf": secrets.token_urlsafe(24),
                     "tokens": {"login": tok["access_token"]}, "threads": {}, "created": time.time()}
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="strict", secure=SECURE, path="/")
    return resp


@app.get("/api/me")
def me(req: Request):
    s = session_of(req)
    return {"sub": s["sub"], "preferred_username": s["username"], "csrf_token": s["csrf"]}


@app.post("/api/chat")
async def chat(req: Request):
    s = session_of(req)
    csrf_ok(req, s)
    body = await req.json()
    tok = get_token(s, "agent")
    r = httpx.post(f"{AGENT_URL}/v1/runs", json={"message": body["message"]},
                   headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    if r.status_code != 200:
        return JSONResponse({"error": "agent", "status": r.status_code}, status_code=502)
    d = r.json()
    s["threads"][d["thread_id"]] = d["intent"]  # intent tin cay = ban BFF luu, khong tin ban tu trinh duyet
    return {"thread_id": d["thread_id"], "status": d["status"], "intent": d["intent"]}


@app.post("/api/approvals")
async def approvals(req: Request):
    s = session_of(req)
    csrf_ok(req, s)
    body = await req.json()
    intent = s["threads"].get(body.get("thread_id"))
    if not intent or intent["intent_id"] != body.get("intent_id"):
        return JSONResponse({"error": "unknown_thread_or_intent"}, status_code=404)
    sr = httpx.post(f"{SIGNER_URL}/v1/approvals", json={"intent": intent, "decision": body.get("decision")},
                    headers={"Authorization": f"Bearer {get_token(s, 'signer')}"}, timeout=15)
    if sr.status_code != 200:
        return JSONResponse({"error": "signer", "status": sr.status_code, "detail": sr.json()}, status_code=502)
    rr = httpx.post(f"{AGENT_URL}/v1/runs/{body['thread_id']}/resume", json={"approval_jws": sr.json()["approval_jws"]},
                    headers={"Authorization": f"Bearer {get_token(s, 'agent')}"}, timeout=30)
    if rr.status_code != 200:
        return JSONResponse({"error": "agent", "status": rr.status_code}, status_code=502)
    d = rr.json()
    return {"thread_id": d["thread_id"], "status": d["status"], "reason": d.get("reason")}
