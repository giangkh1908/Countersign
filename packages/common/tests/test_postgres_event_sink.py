"""Test với Postgres thật; bỏ qua nếu không có TEST_DATABASE_URL (vd postgresql://postgres:pw@localhost:55432/postgres).

Mỗi test chạy trong một schema riêng (DDL mô phỏng contracts §3.1/§3.6, gồm trigger append-only).
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from urllib.parse import quote

import psycopg
import pytest
from acme_common.adapters.audit_pg import append_audit, fetch_rows
from acme_common.adapters.postgres_event_sink import PostgresEventSink
from acme_common.mcp import CallerContext, ToolInvoker
from acme_common.mcp.context import AuthContext, reset_auth, set_auth
from acme_common.ports import Principal, ToolSpec
from acme_common.services.audit_chain import AuditKeyring, verify_chain
from acme_common.testing import FakeClock, FakeRateLimiter

BASE = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def event_loop_policy():
    """psycopg async không chạy trên ProactorEventLoop (Windows)."""
    import asyncio
    import sys

    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


KR = AuditKeyring.single("a" * 32, 1)

DDL = """
CREATE SEQUENCE audit_log_id_seq; CREATE SEQUENCE tool_audit_id_seq;
CREATE TABLE audit_log (
  id bigint PRIMARY KEY DEFAULT nextval('audit_log_id_seq'), ts timestamptz NOT NULL,
  request_id uuid, actor_type text NOT NULL, actor_id text NOT NULL, end_user_sub text,
  action text NOT NULL, resource text, decision text NOT NULL CHECK (decision IN ('allow','deny','error')),
  details jsonb NOT NULL DEFAULT '{}', hmac_kid smallint NOT NULL, prev_hash bytea NOT NULL, hash bytea NOT NULL);
CREATE TABLE tool_audit (
  id bigint PRIMARY KEY DEFAULT nextval('tool_audit_id_seq'), ts timestamptz NOT NULL,
  request_id uuid, actor_type text NOT NULL, actor_id text NOT NULL, end_user_sub text,
  action text NOT NULL, resource text, decision text NOT NULL CHECK (decision IN ('allow','deny','error')),
  details jsonb NOT NULL DEFAULT '{}', intent_id uuid NULL,
  hmac_kid smallint NOT NULL, prev_hash bytea NOT NULL, hash bytea NOT NULL);
CREATE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION '% on % not allowed', TG_OP, TG_TABLE_NAME USING ERRCODE = '42501'; END $$;
CREATE TRIGGER tool_audit_no_mod BEFORE UPDATE OR DELETE ON tool_audit
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TABLE usage_events (
  id bigserial, ts timestamptz NOT NULL DEFAULT now(), request_id uuid NOT NULL, key_id uuid NOT NULL,
  department text NOT NULL, end_user_sub text, alias text NOT NULL, provider text, model text,
  input_tokens int, output_tokens int, cached_input_tokens int, cost_micro_usd bigint NOT NULL DEFAULT 0,
  latency_ms int, ttft_ms int, gateway_overhead_ms int,
  cache text NOT NULL DEFAULT 'miss', fallback_count smallint NOT NULL DEFAULT 0, route_reason text,
  status_code smallint NOT NULL, error_code text,
  PRIMARY KEY (id, ts));
CREATE TABLE tickets (id int PRIMARY KEY, status text NOT NULL);
"""


@pytest.fixture
def dsn() -> Iterator[str]:
    assert BASE
    schema = "t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(BASE, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {schema}")
    opts = quote(f"-csearch_path={schema}", safe="")
    sep = "&" if "?" in BASE else "?"
    url = f"{BASE}{sep}options={opts}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(DDL)
    yield url
    with psycopg.connect(BASE, autocommit=True) as c:
        c.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture
async def aconn(dsn: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as c:
        yield c


def usage(i: int = 0) -> dict:
    return {
        "event": "usage_event", "request_id": str(uuid.uuid4()), "key_id": str(uuid.uuid4()),
        "department": "CS", "alias": "acme-fast", "input_tokens": 10 + i, "status_code": 200,
        "cost_micro_usd": 5,
    }  # fmt: skip


def audit(i: int = 0, event: str = "tool_audit") -> dict:
    return {
        "event": event, "request_id": str(uuid.uuid4()), "actor_type": "service",
        "actor_id": "agent-service", "end_user_sub": "u1", "action": "tool.call",
        "resource": f"t{i}", "decision": "allow", "details": {"i": i, "s": "Đã đóng"},
    }  # fmt: skip


async def test_usage_batched_on_flush(dsn: str, aconn) -> None:
    sink = PostgresEventSink(dsn, KR, batch_size=1000)
    for i in range(25):
        sink.append(usage(i))
    cur = await aconn.execute("SELECT count(*) FROM usage_events")
    assert (await cur.fetchone())[0] == 0  # chưa flush => chưa ghi
    await sink.flush()
    cur = await aconn.execute("SELECT count(*), sum(input_tokens) FROM usage_events")
    assert await cur.fetchone() == (25, sum(10 + i for i in range(25)))


async def test_usage_auto_flush_when_batch_full(dsn: str, aconn) -> None:
    sink = PostgresEventSink(dsn, KR, batch_size=5)
    for i in range(5):
        sink.append(usage(i))  # không chặn: flush chạy ở thread nền
    for _ in range(50):
        cur = await aconn.execute("SELECT count(*) FROM usage_events")
        if (await cur.fetchone())[0] == 5:
            break
        await asyncio.sleep(0.1)
    assert (await cur.fetchone())[0] == 5


async def test_usage_kept_in_buffer_when_db_down() -> None:
    sink = PostgresEventSink("postgresql://x:y@127.0.0.1:1/none", KR, connect_timeout_s=1)
    sink.append(usage())
    await sink.flush(timeout_s=5)
    assert sink.write_failures == 1 and len(sink._usage) == 1  # noqa: SLF001


async def test_audit_sync_chain_verifies_and_detects_tamper(dsn: str, aconn) -> None:
    sink = PostgresEventSink(dsn, KR)
    for i in range(6):
        sink.append(audit(i), sync=True)
    sink.append(audit(6, "audit_log"), sync=True)
    rows = await fetch_rows(aconn, "tool_audit")
    assert len(rows) == 6 and verify_chain(rows, KR).ok
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert verify_chain(await fetch_rows(aconn, "audit_log"), KR).ok

    # trigger chặn UPDATE thường
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await aconn.execute("UPDATE tool_audit SET decision='deny' WHERE id=%s", (rows[2]["id"],))
    # kẻ có quyền DBA tắt trigger rồi sửa/xoá: verify phải bắt được
    await aconn.execute("ALTER TABLE tool_audit DISABLE TRIGGER tool_audit_no_mod")
    await aconn.execute("UPDATE tool_audit SET decision='deny' WHERE id=%s", (rows[2]["id"],))
    r = verify_chain(await fetch_rows(aconn, "tool_audit"), KR)
    assert not r.ok and r.reason == "hash_mismatch" and r.bad_id == rows[2]["id"]
    await aconn.execute("UPDATE tool_audit SET decision='allow' WHERE id=%s", (rows[2]["id"],))
    assert verify_chain(await fetch_rows(aconn, "tool_audit"), KR).ok
    await aconn.execute("DELETE FROM tool_audit WHERE id=%s", (rows[3]["id"],))
    r = verify_chain(await fetch_rows(aconn, "tool_audit"), KR)
    assert not r.ok and r.reason == "chain_break" and r.bad_id == rows[4]["id"]


async def test_audit_concurrent_writers_keep_single_chain(dsn: str, aconn) -> None:
    sinks = [PostgresEventSink(dsn, KR) for _ in range(4)]

    def work(s: PostgresEventSink, k: int) -> None:
        for i in range(10):
            s.append(audit(k * 100 + i), sync=True)

    ts = [threading.Thread(target=work, args=(s, k)) for k, s in enumerate(sinks)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    rows = await fetch_rows(aconn, "tool_audit")
    assert len(rows) == 40 and verify_chain(rows, KR).ok


async def test_audit_buffered_non_sync_written_on_flush(dsn: str, aconn) -> None:
    sink = PostgresEventSink(dsn, KR)
    sink.append(audit(1))
    sink.append(audit(2))
    assert not await fetch_rows(aconn, "tool_audit")
    await sink.flush()
    assert len(await fetch_rows(aconn, "tool_audit")) == 2


async def test_audit_in_callers_transaction_rolls_back_with_update(dsn: str, aconn) -> None:
    await aconn.execute("INSERT INTO tickets VALUES (1, 'open')")

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        async with aconn.transaction():
            await aconn.execute("UPDATE tickets SET status='closed' WHERE id=1")
            await append_audit(aconn, "tool_audit", audit(1), KR)
            raise Boom
    assert (await (await aconn.execute("SELECT status FROM tickets")).fetchone())[0] == "open"
    assert not await fetch_rows(aconn, "tool_audit")

    iid = str(uuid.uuid4())
    async with aconn.transaction():
        await aconn.execute("UPDATE tickets SET status='closed' WHERE id=1")
        await append_audit(aconn, "tool_audit", {**audit(2), "intent_id": iid}, KR)
    rows = await fetch_rows(aconn, "tool_audit")
    assert len(rows) == 1 and str(rows[0]["intent_id"]) == iid and verify_chain(rows, KR).ok


async def test_tool_invoker_writes_chain_through_postgres_sink(dsn: str, aconn) -> None:
    sink = PostgresEventSink(dsn, KR)
    clock = FakeClock()
    inv = ToolInvoker(server="docs-mcp", limiter=FakeRateLimiter(), audit=sink, clock=clock)
    spec = ToolSpec(name="t", description="d", input_schema={"type": "object"})

    async def h(ctx: CallerContext, args: dict) -> dict:
        return {"ok": True}

    p = Principal("u1", ("docs-mcp",), "agent-service", frozenset(), 9e9)
    tok = set_auth(AuthContext(p, str(uuid.uuid4())))
    try:
        for _ in range(3):
            await inv.wrap(spec, h)({}, {})
    finally:
        reset_auth(tok)
    rows = await fetch_rows(aconn, "tool_audit")
    assert len(rows) == 3 and verify_chain(rows, KR).ok and inv.audit_failures == 0
