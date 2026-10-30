"""Ghi hàng audit có hash-chain vào Postgres, TRONG transaction của caller (D6, 02 §6.8).

Caller truyền connection đang mở transaction; hàm KHÔNG commit/rollback. Nhờ vậy tickets-mcp ghi
`tool_audit` cùng transaction với UPDATE: lỗi audit => rollback cả hai.

Chuỗi toàn cục tuần tự hoá bằng `pg_advisory_xact_lock`; `id` lấy từ sequence SAU khi giữ khoá nên
thứ tự id == thứ tự chuỗi. Driver: psycopg 3 (có bản async và sync, cùng logic).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection, Connection
from psycopg.types.json import Jsonb

from .chain import GENESIS_HASH, AuditKeyring, seal

# bảng -> (sequence, có cột intent_id). Whitelist: tên bảng không bao giờ lấy từ input.
AUDIT_TABLES: dict[str, tuple[str, bool]] = {
    "audit_log": ("audit_log_id_seq", False),
    "tool_audit": ("tool_audit_id_seq", True),
}
_REQUIRED = ("actor_type", "actor_id", "action", "decision")


def _build_row(table: str, record: Mapping[str, Any], row_id: int) -> dict[str, Any]:
    _, has_intent = AUDIT_TABLES[table]
    for f in _REQUIRED:
        if not record.get(f):
            raise ValueError(f"audit record missing {f!r}")
    ts = record.get("ts") or datetime.now(UTC)
    row: dict[str, Any] = {
        "id": row_id,
        "ts": ts,
        "request_id": record.get("request_id"),
        "actor_type": record["actor_type"],
        "actor_id": record["actor_id"],
        "end_user_sub": record.get("end_user_sub"),
        "action": record["action"],
        "resource": record.get("resource"),
        "decision": record["decision"],
        "details": dict(record.get("details") or {}),
    }
    if has_intent:
        row["intent_id"] = record.get("intent_id")
    return row


def _insert_sql(table: str, row: Mapping[str, Any]) -> tuple[str, list[Any]]:
    cols = [
        "id", "ts", "request_id", "actor_type", "actor_id", "end_user_sub", "action",
        "resource", "decision", "details", "hmac_kid", "prev_hash", "hash",
    ]  # fmt: skip
    if "intent_id" in row:
        cols.insert(10, "intent_id")
    vals: list[Any] = []
    for c in cols:
        v = row[c]
        if c == "details":
            v = Jsonb(v)
        elif c in ("request_id", "intent_id") and v is not None:
            v = uuid.UUID(str(v))
        vals.append(v)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
    return sql, vals


_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"


async def append_audit(
    conn: AsyncConnection[Any], table: str, record: Mapping[str, Any], keyring: AuditKeyring
) -> dict[str, Any]:
    """Ghi 1 hàng; trả row đã niêm phong (id, ts, hmac_kid, prev_hash, hash...)."""
    seq, _ = AUDIT_TABLES[table]
    await conn.execute(_LOCK_SQL, (table,))  # type: ignore[arg-type]
    cur = await conn.execute(f"SELECT hash FROM {table} ORDER BY id DESC LIMIT 1")  # type: ignore[call-overload]
    last = await cur.fetchone()
    prev = bytes(last[0]) if last else GENESIS_HASH
    cur = await conn.execute("SELECT nextval(%s)", (seq,))
    row_id = (await cur.fetchone())[0]  # type: ignore[index]
    row = seal(keyring, prev, _build_row(table, record, int(row_id)))
    sql, vals = _insert_sql(table, row)
    await conn.execute(sql, vals)  # type: ignore[arg-type]
    return row


def append_audit_sync(
    conn: Connection[Any], table: str, record: Mapping[str, Any], keyring: AuditKeyring
) -> dict[str, Any]:
    seq, _ = AUDIT_TABLES[table]
    conn.execute(_LOCK_SQL, (table,))  # type: ignore[arg-type]
    last = conn.execute(f"SELECT hash FROM {table} ORDER BY id DESC LIMIT 1").fetchone()  # type: ignore[call-overload]
    prev = bytes(last[0]) if last else GENESIS_HASH
    row_id = conn.execute("SELECT nextval(%s)", (seq,)).fetchone()[0]  # type: ignore[index]
    row = seal(keyring, prev, _build_row(table, record, int(row_id)))
    sql, vals = _insert_sql(table, row)
    conn.execute(sql, vals)  # type: ignore[arg-type]
    return row


_SELECT_COLS = (
    "id, ts, request_id, actor_type, actor_id, end_user_sub, action, resource, decision, "
    "details, {intent}hmac_kid, prev_hash, hash"
)


def select_sql(table: str, *, after_id: int = 0) -> str:
    """SQL đọc các hàng theo thứ tự chuỗi để đưa vào `verify_chain` (`WHERE id > after_id`)."""
    _, has_intent = AUDIT_TABLES[table]
    cols = _SELECT_COLS.format(intent="intent_id, " if has_intent else "")
    return f"SELECT {cols} FROM {table} WHERE id > {int(after_id)} ORDER BY id"


async def fetch_rows(
    conn: AsyncConnection[Any], table: str, *, after_id: int = 0
) -> list[dict[str, Any]]:
    cur = await conn.execute(select_sql(table, after_id=after_id))  # type: ignore[call-overload]
    names = [d.name for d in cur.description or ()]
    return [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]
