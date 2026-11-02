"""Postgres thật: RLS khớp ma trận quyền ở MỌI ô, và adapter ghi/tạo ticket qua RLS.

Bỏ qua nếu không có TEST_DATABASE_URL (superuser, vd postgresql://postgres:pw@localhost:55432/postgres).
Mỗi lần chạy tạo một database riêng, áp `30-tickets.sql` nguyên văn, rồi xoá.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
import pytest
from acme_common.ports import Approval, Principal
from acme_common.services.audit_chain import AuditKeyring
from mcp_tickets.adapters.postgres_tickets import PostgresTicketRepository
from mcp_tickets.ports import DuplicateIntent, Intent
from psycopg import errors as pgerr
from test_roles_matrix import CASES, COLLEAGUE, ME

BASE = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="TEST_DATABASE_URL not set")

SQL = Path(__file__).parents[3] / "infra" / "postgres" / "init" / "sql" / "30-tickets.sql"
APP_PW = "tk-app-test-pw"
KR = AuditKeyring.single("a" * 32, 1)


def _dsn(db: str, user: str | None = None, pw: str | None = None) -> str:
    u = urlsplit(BASE or "")
    netloc = u.netloc
    if user:
        netloc = f"{user}:{quote(pw or '')}@{u.hostname}:{u.port}"
    return urlunsplit((u.scheme, netloc, f"/{db}", "", ""))


@pytest.fixture(scope="module")
def db() -> Iterator[str]:
    name = "tk_" + uuid.uuid4().hex[:10]
    with psycopg.connect(_dsn("postgres"), autocommit=True) as admin:
        for role in ("tk_owner", "tk_app", "mcp_audit_w"):
            admin.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
            )
        admin.execute(f"ALTER ROLE tk_app PASSWORD '{APP_PW}'")
        admin.execute(f"CREATE DATABASE {name} OWNER tk_owner")
    try:
        with psycopg.connect(_dsn(name), autocommit=True) as conn:
            conn.execute(re.sub(r"DATABASE tickets", f"DATABASE {name}", SQL.read_text("utf-8")))
            conn.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tk_app")
            seed = [
                ("TCK-000500", ME, "SALES"),  # giao cho ME
                ("TCK-000501", COLLEAGUE, "SALES"),  # đồng nghiệp cùng phòng
                ("TCK-000502", COLLEAGUE, "HR"),  # phòng khác
            ]
            for code, assignee, dept in seed:
                conn.execute(
                    "INSERT INTO tickets (code, title, description, status, priority, category, "
                    "requester_sub, requester_dept, assignee_sub, assignee_dept) "
                    "VALUES (%s, 't', 'd', 'in_progress', 'low', 'other', 'u-req', %s, %s, %s)",
                    (code, dept, assignee, dept),
                )
        yield name
    finally:
        with psycopg.connect(_dsn("postgres"), autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _as_app(conn: psycopg.Connection, roles: tuple[str, ...], dept: str = "SALES") -> None:
    conn.execute("SET LOCAL ROLE tk_app")
    conn.execute(
        "SELECT set_config('app.sub', %s, true), set_config('app.depts', %s, true), "
        "set_config('app.roles', %s, true)",
        (ME, dept, ",".join(roles)),
    )


def _try_insert(conn: psycopg.Connection) -> bool:
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO tickets (code, title, description, status, priority, category, "
                "requester_sub, requester_dept, assignee_dept) "
                "VALUES ('', 't', 'd', 'open', 'low', 'other', %s, 'SALES', 'HR')",
                (ME,),
            )
        return True
    except pgerr.InsufficientPrivilege:
        return False


def _try_close(conn: psycopg.Connection, code: str) -> bool:
    with conn.transaction():
        cur = conn.execute(
            "UPDATE tickets SET status = 'closed', updated_at = now() WHERE code = %s", (code,)
        )
        return cur.rowcount == 1


@pytest.mark.parametrize("name", sorted(CASES))
def test_rls_create_cell(db: str, name: str) -> None:
    roles, (can_create, _, _) = CASES[name]
    with psycopg.connect(_dsn(db), autocommit=False) as conn:
        _as_app(conn, roles)
        assert _try_insert(conn) is can_create
        conn.rollback()


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize(
    ("scenario", "code", "dept"),
    [("assigned", "TCK-000500", "SALES"), ("in_dept", "TCK-000501", "SALES")],
)
def test_rls_close_cell(db: str, name: str, scenario: str, code: str, dept: str) -> None:
    roles, (_, can_assigned, can_dept) = CASES[name]
    with psycopg.connect(_dsn(db), autocommit=False) as conn:
        _as_app(conn, roles, dept)
        assert _try_close(conn, code) is (can_assigned if scenario == "assigned" else can_dept)
        conn.rollback()


@pytest.mark.parametrize("name", sorted(CASES))
def test_rls_never_closes_other_dept(db: str, name: str) -> None:
    roles, _ = CASES[name]
    with psycopg.connect(_dsn(db), autocommit=False) as conn:
        _as_app(conn, roles, "SALES")
        assert _try_close(conn, "TCK-000502") is False
        conn.rollback()


def test_rls_insert_must_be_own_requester_and_open(db: str) -> None:
    with psycopg.connect(_dsn(db), autocommit=False) as conn:
        _as_app(conn, ("employee",))
        for sub, status in [("someone-else", "open"), (ME, "closed")]:
            with pytest.raises(pgerr.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    "INSERT INTO tickets (code, title, description, status, priority, category, "
                    "requester_sub, requester_dept, assignee_dept) "
                    "VALUES ('', 't', 'd', %s, 'low', 'other', %s, 'SALES', 'HR')",
                    (status, sub),
                )
        conn.rollback()


def test_rls_read_rights_unchanged_for_admin_and_management(db: str) -> None:
    def visible(roles: tuple[str, ...], dept: str = "SALES") -> int:
        with psycopg.connect(_dsn(db), autocommit=False) as conn:
            _as_app(conn, roles, dept)
            n = conn.execute("SELECT count(*) FROM tickets").fetchone()[0]  # type: ignore[index]
            conn.rollback()
            return int(n)

    assert visible(("employee", "admin")) >= 3  # admin vẫn xem hết
    assert visible(("management",)) == 2  # ticket trong phòng, sửa lệch số 3
    assert visible(("auditor",)) == 0


# ---------------------------------------------------------------- adapter qua RLS
def _principal(roles: tuple[str, ...]) -> Principal:
    return Principal(
        ME, ("tickets-mcp",), "agent-service", frozenset(), 0.0, dept=("SALES",), roles=roles
    )


def _repo(db: str) -> PostgresTicketRepository:
    return PostgresTicketRepository(_dsn(db, "tk_app", APP_PW), KR)


def _intent(op: str, args: dict, code: str | None = None, expected: str | None = None) -> Intent:
    target = {"ticket_code": code} if code else {}
    return Intent(str(uuid.uuid4()), op, "f" * 64, ME, args, {}, {"status": "x"}, expected, target)


async def test_adapter_creates_ticket_with_code_at_commit(db: str) -> None:
    repo = _repo(db)
    args = {
        "title": "Vé mới",
        "body": "Mô tả",
        "category": "other",
        "priority": "low",
        "assignee_dept": "HR",
        "classification": 1,
    }
    intent = _intent("create_ticket", args)
    ap = Approval(str(uuid.uuid4()), intent.intent_id, "f" * 64)
    done = await repo.commit_write(intent, ap, _principal(("employee",)))
    assert done.op == "create_ticket" and done.ticket is not None
    assert re.fullmatch(r"TCK-\d{6}", done.ticket.code) and done.ticket.status == "open"
    assert (done.ticket.requester_sub, done.ticket.requester_dept) == (ME, "SALES")
    found = await repo.find_applied(intent.intent_id, _principal(("employee",)))
    assert (
        found is not None and found.op == "create_ticket" and found.ticket_code == done.ticket.code
    )
    # cùng intent_id lần hai: UNIQUE chặn, và ticket vừa chèn bị rollback theo
    with pytest.raises(DuplicateIntent):
        await repo.commit_write(
            intent,
            Approval(str(uuid.uuid4()), intent.intent_id, "f" * 64),
            _principal(("employee",)),
        )
    with psycopg.connect(_dsn(db)) as c:
        n = c.execute("SELECT count(*) FROM tickets WHERE title = 'Vé mới'").fetchone()[0]  # type: ignore[index]
    assert n == 1


async def test_adapter_denied_roles_write_nothing(db: str) -> None:
    from mcp_tickets.ports import RepositoryRolledBack, TicketConflict

    repo = _repo(db)
    args = {"title": "x", "body": "y", "category": "other", "priority": "low",
            "assignee_dept": "HR", "classification": 1}  # fmt: skip
    intent = _intent("create_ticket", args)
    ap = Approval(str(uuid.uuid4()), intent.intent_id, "f" * 64)
    with psycopg.connect(_dsn(db)) as c:
        before = c.execute("SELECT count(*) FROM tickets").fetchone()[0]  # type: ignore[index]
        events = c.execute("SELECT count(*) FROM ticket_events").fetchone()[0]  # type: ignore[index]
    for roles in (("employee", "admin"), ("auditor",)):
        with pytest.raises(RepositoryRolledBack):
            await repo.commit_write(intent, ap, _principal(roles))
    close = _intent("close_ticket", {"code": "TCK-000500", "resolution": "xong rồi nhé"},
                    "TCK-000500", "2020-01-01T00:00:00.000000Z")  # fmt: skip
    for roles in (("employee", "admin"), ("auditor",)):
        with pytest.raises(TicketConflict):
            await repo.commit_write(close, ap, _principal(roles))
    with psycopg.connect(_dsn(db)) as c:
        assert c.execute("SELECT count(*) FROM tickets").fetchone()[0] == before  # type: ignore[index]
        assert c.execute("SELECT count(*) FROM ticket_events").fetchone()[0] == events  # type: ignore[index]
