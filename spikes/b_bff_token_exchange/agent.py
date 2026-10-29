"""agent-service toi thieu: FastAPI + LangGraph (interrupt/Command) + InMemorySaver."""
import time, uuid
from typing import TypedDict
import jwt
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from jwt import PyJWKClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
import common
from signer import intent_sha256

SIGNER_JWKS = "http://127.0.0.1:8311/v1/jwks"  # run_cases co the dat lai
LAST_BEARER = None  # mo phong "agent bi chiem": token gan nhat agent dang cam
OWNERS: dict = {}   # thread_id -> sub


class S(TypedDict, total=False):
    message: str
    sub: str
    intent: dict
    decision: str
    result: str
    reason: str


def plan(s: S):
    intent = {"intent_id": uuid.uuid4().hex, "sub": s["sub"], "op": "tickets.close", "target": "TCK-1001",
              "args": {"resolution": "fixed", "note": s["message"]}, "exp": int(time.time()) + 600}
    return {"intent": intent}


def verify_approval(jws: str, intent: dict, sub: str) -> dict:
    key = PyJWKClient(SIGNER_JWKS).get_signing_key_from_jwt(jws).key
    c = jwt.decode(jws, key, algorithms=["ES256"], issuer="approval-signer",
                   options={"require": ["exp", "iss", "sub"]})
    if c["intent_sha256"] != intent_sha256(intent):
        raise ValueError("intent_sha256 lech")
    if c["intent_id"] != intent["intent_id"]:
        raise ValueError("intent_id lech")
    if c["sub"] != sub:
        raise ValueError("sub lech")
    if intent["exp"] < time.time():
        raise ValueError("intent het han")
    if c["decision"] not in ("approve", "reject"):
        raise ValueError("decision la")
    return c


def gate(s: S):
    resp = interrupt({"intent": s["intent"]})
    try:
        c = verify_approval(resp["approval_jws"], s["intent"], s["sub"])
    except Exception as e:
        return {"result": "refused", "reason": f"{type(e).__name__}: {e}", "decision": "none"}
    return {"decision": c["decision"], "result": "rejected" if c["decision"] == "reject" else "pending"}


def execute(s: S):
    return {"result": "executed"}  # gia lap: that thi goi tickets-mcp


g = StateGraph(S)
g.add_node("plan", plan)
g.add_node("gate", gate)
g.add_node("execute", execute)
g.add_edge(START, "plan")
g.add_edge("plan", "gate")
g.add_conditional_edges("gate", lambda s: "execute" if s.get("decision") == "approve" else END, ["execute", END])
g.add_edge("execute", END)
GRAPH = g.compile(checkpointer=InMemorySaver())

app = FastAPI()


def auth(req: Request) -> dict:
    global LAST_BEARER
    h = req.headers.get("authorization", "")
    if not h.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer")
    try:
        c = common.verify_kc_token(h[7:])
    except Exception as e:
        raise HTTPException(401, f"invalid token: {e}")
    if "agent-service" not in common.aud_list(c):
        raise HTTPException(401, f"aud={c.get('aud')} khong chua agent-service")
    LAST_BEARER = h[7:]
    return c


def out(cfg):
    st = GRAPH.get_state(cfg)
    if st.next:  # dang dung o interrupt
        return {"status": "interrupted", "intent": st.tasks[0].interrupts[0].value["intent"]}
    return {"status": st.values.get("result"), "reason": st.values.get("reason")}


@app.post("/v1/runs")
async def runs(req: Request):
    c = auth(req)
    body = await req.json()
    tid = uuid.uuid4().hex
    OWNERS[tid] = c["sub"]
    cfg = {"configurable": {"thread_id": tid}}
    GRAPH.invoke({"message": body["message"], "sub": c["sub"]}, cfg)
    return {"thread_id": tid, **out(cfg)}


@app.post("/v1/runs/{tid}/resume")
async def resume(tid: str, req: Request):
    c = auth(req)
    body = await req.json()
    if OWNERS.get(tid) != c["sub"]:
        return JSONResponse({"error": "not_owner"}, status_code=403)
    cfg = {"configurable": {"thread_id": tid}}
    GRAPH.invoke(Command(resume={"approval_jws": body.get("approval_jws", "")}), cfg)
    return {"thread_id": tid, **out(cfg)}
