"""Sổ `report_deliveries` trên Postgres thật. Bỏ qua nếu không có `TEST_NOTIFY_PG_SUPERUSER_DSN`.

DSN này là siêu người dùng của một Postgres dùng-một-lần (vd `docker run --rm`): test TẠO DB `notify`
và các role `nt_owner`, `nt_app`, `mcp_audit_w`, rồi chạy `infra/postgres/init/sql/30-notify.sql`.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from acme_common.ports import DuplicateIntent
from mcp_notify.adapters.postgres_deliveries import PostgresDeliveryLog
from mcp_notify.ports import DeliveryLogUnavailable

SUPER = os.environ.get("TEST_NOTIFY_PG_SUPERUSER_DSN")
pytestmark = pytest.mark.skipif(not SUPER, reason="cần TEST_NOTIFY_PG_SUPERUSER_DSN")
SQL = Path(__file__).resolve().parents[3] / "infra/postgres/init/sql/30-notify.sql"
PW = "test-pw-123"


def _with_db(dsn: str, db: str, user: str | None = None, pw: str | None = None) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    d = conninfo_to_dict(dsn)
    d["dbname"] = db
    if user:
        d["user"], d["password"] = user, pw
    return make_conninfo(**d)


@pytest.fixture(scope="module")
def dsn_app() -> str:
    import psycopg

    assert SUPER
    with psycopg.connect(_with_db(SUPER, "postgres"), autocommit=True) as c:
        for role in ("nt_owner", "nt_app", "mcp_audit_w"):
            exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if not exists:
                c.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{PW}'")
        c.execute("DROP DATABASE IF EXISTS notify")
        c.execute("CREATE DATABASE notify OWNER nt_owner")
    with psycopg.connect(_with_db(SUPER, "notify"), autocommit=True) as c:
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        c.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        c.execute(SQL.read_text(encoding="utf-8"))
        c.execute(SQL.read_text(encoding="utf-8"))  # idempotent: chạy lại không lỗi
    return _with_db(SUPER, "notify", "nt_app", PW)


@pytest.fixture
def log(dsn_app: str) -> PostgresDeliveryLog:
    return PostgresDeliveryLog(dsn_app)


def iid() -> str:
    return str(uuid.uuid4())


async def test_begin_finish_find(log: PostgresDeliveryLog) -> None:
    i = iid()
    await log.begin(i, "dept-eng", "a" * 64, "u1", iid())
    r = await log.find(i)
    assert r and r.status == "sending" and r.channel == "dept-eng" and r.text_sha256 == "a" * 64
    await log.finish(i, "sent", "ok")
    r = await log.find(i)
    assert r and r.status == "sent"
    assert await log.find(iid()) is None


async def test_unique_intent_blocks_second_begin(log: PostgresDeliveryLog) -> None:
    i = iid()
    await log.begin(i, "dept-eng", "b" * 64, "u1", iid())
    with pytest.raises(DuplicateIntent):
        await log.begin(i, "dept-eng", "b" * 64, "u1", iid())


async def test_final_status_cannot_change(log: PostgresDeliveryLog) -> None:
    i = iid()
    await log.begin(i, "dept-eng", "c" * 64, "u1", iid())
    await log.finish(i, "unknown", "timeout")
    await log.finish(i, "sent")  # không đổi được trạng thái cuối (adapter nuốt hoặc trigger chặn)
    r = await log.find(i)
    assert r and r.status == "unknown"


def test_app_role_cannot_delete_or_edit_immutable_columns(dsn_app: str) -> None:
    import psycopg
    from psycopg import errors

    i = iid()
    with psycopg.connect(dsn_app, autocommit=True) as c:
        c.execute(
            "INSERT INTO report_deliveries (intent_id, channel, text_sha256, actor_sub, approval_jti, status)"
            " VALUES (%s, 'dept-eng', %s, 'u1', %s, 'sending')",
            (i, "d" * 64, iid()),
        )
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("DELETE FROM report_deliveries WHERE intent_id = %s", (i,))
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute(
                "UPDATE report_deliveries SET channel = 'company-all' WHERE intent_id = %s", (i,)
            )
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("TRUNCATE report_deliveries")
        with pytest.raises(errors.CheckViolation):
            c.execute("UPDATE report_deliveries SET status = 'weird' WHERE intent_id = %s", (i,))


async def test_unreachable_database_is_not_written() -> None:
    bad = PostgresDeliveryLog("postgresql://x:y@127.0.0.1:1/notify?connect_timeout=1")
    with pytest.raises(DeliveryLogUnavailable) as e:
        await bad.begin(iid(), "dept-eng", "e" * 64, "u1", iid())
    assert e.value.not_written is True
