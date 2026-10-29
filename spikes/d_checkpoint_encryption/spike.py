"""Spike D: LangGraph checkpoint encryption on Postgres. Modes: phase1 | resume | wrongkey | inspect | all"""
import json, os, subprocess, sys, uuid
from typing import Annotated, TypedDict
import psycopg
from psycopg.rows import dict_row
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

DSN = os.environ.get("SPIKE_D_DSN") or (
    f"postgresql://postgres:{os.environ['SPIKE_D_PG_PASSWORD']}@localhost:55432/postgres"
)
SECRET = "SECRET-TCK-000123-salary"
KEY = "k" * 32  # 32 raw bytes
BAD = "x" * 32

class S(TypedDict):
    messages: Annotated[list, add_messages]
    note: str      # small primitive channel (test inlining into JSONB)
    box: list      # same secret wrapped in a list (non-primitive -> should go to blob)
    decision: str

def node_a(s):
    return {"messages": [HumanMessage(SECRET + " luong cua nhan vien")], "note": SECRET + "-note", "box": [SECRET + "-box"]}
def node_b(s):
    d = interrupt({"intent_id": "i1", "payload": SECRET + "-interrupt"})
    return {"decision": str(d)}
def node_c(s):
    return {"messages": [HumanMessage("C ran, decision=" + s["decision"])]}

def build(saver):
    g = StateGraph(S)
    g.add_node("A", node_a); g.add_node("B", node_b); g.add_node("C", node_c)
    g.add_edge(START, "A"); g.add_edge("A", "B"); g.add_edge("B", "C"); g.add_edge("C", END)
    return g.compile(checkpointer=saver)

def saver_for(conn, mode, key=KEY):
    if mode == "plain":
        return PostgresSaver(conn)
    if mode == "b64":  # key from base64 env var, passed as bytes (no LANGGRAPH_AES_KEY)
        import base64
        raw = base64.b64decode(base64.b64encode(key.encode()))
        return PostgresSaver(conn, serde=EncryptedSerializer.from_pycryptodome_aes(key=raw))
    os.environ["LANGGRAPH_AES_KEY"] = key
    return PostgresSaver(conn, serde=EncryptedSerializer.from_pycryptodome_aes())

def connect():
    return psycopg.connect(DSN, autocommit=True, row_factory=dict_row)

def cfg(tid):
    # 'user_note' in configurable to see whether configurable leaks into metadata
    return {"configurable": {"thread_id": tid, "user_note": SECRET + "-configurable"}}

def main():
    mode, tid, what = sys.argv[1], sys.argv[2], sys.argv[3]
    with connect() as conn:
        if what == "phase1":
            sv = saver_for(conn, mode); sv.setup()
            g = build(sv); r = g.invoke({"messages": [], "note": "", "box": [], "decision": ""}, cfg(tid))
            print("phase1 interrupt:", r.get("__interrupt__"))
        elif what in ("resume", "wrongkey"):
            sv = saver_for(conn, mode, KEY if what == "resume" else BAD)
            g = build(sv)
            try:
                if what == "wrongkey":
                    print("get_state:", g.get_state(cfg(tid)).values)
                else:
                    r = g.invoke(Command(resume="approved"), cfg(tid))
                    print("resume final messages:", [m.content for m in r["messages"]], "decision:", r["decision"])
            except Exception as e:
                print("ERROR", type(e).__module__ + "." + type(e).__name__, str(e)[:200])

def run(mode, tid, what):
    p = subprocess.run([sys.executable, __file__, mode, tid, what], capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip().splitlines()
    print(f"[{mode}/{what} pid-separate rc={p.returncode}]", *out[-3:], sep="\n  ")

def inspect(tid):
    with connect() as c:
        for tbl, cols in [("checkpoints", ["checkpoint::text", "metadata::text"]),
                          ("checkpoint_blobs", ["encode(blob,'escape')"]),
                          ("checkpoint_writes", ["encode(blob,'escape')"])]:
            for col in cols:
                n = c.execute(f"select count(*) n, count(*) filter (where position(%s in {col})>0) h from {tbl} where thread_id=%s", (SECRET, tid)).fetchone()
                print(f"  {tbl}.{col.split('::')[0].split('(')[0] if 'blob' not in col else 'blob'}{'(metadata)' if 'metadata' in col else ''}: rows={n['n']} with_secret={n['h']}")
        print("  checkpoints.checkpoint channel_values:", c.execute("select checkpoint->'channel_values' v from checkpoints where thread_id=%s order by checkpoint_id desc limit 1", (tid,)).fetchone()["v"])
        print("  latest metadata:", c.execute("select metadata::text m from checkpoints where thread_id=%s order by checkpoint_id desc limit 1", (tid,)).fetchone()["m"])
        print("  blob types/channels:", [(r['channel'], r['type'], r['len']) for r in c.execute("select channel,type,length(blob) len from checkpoint_blobs where thread_id=%s", (tid,))])
        print("  writes channels:", [(r['channel'], r['type']) for r in c.execute("select channel,type from checkpoint_writes where thread_id=%s", (tid,))])

if __name__ == "__main__":
    if len(sys.argv) > 3:
        main()
    else:
        with connect() as c:
            c.execute("drop table if exists checkpoint_migrations, checkpoints, checkpoint_blobs, checkpoint_writes")
        for mode in ("enc", "plain", "b64"):
            tid = f"{mode}-{uuid.uuid4()}"
            print(f"\n=== {mode} thread {tid}")
            run(mode, tid, "phase1")
            print(" after phase1 (graph paused at interrupt):"); inspect(tid)
            if mode in ("enc", "b64"):
                run(mode, tid, "wrongkey")
                run(mode, tid, "resume")   # NEW process = restart simulation
            else:
                run(mode, tid, "resume")
