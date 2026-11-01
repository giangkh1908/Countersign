"""Xuất SQL nạp dữ liệu (idempotent: INSERT ... ON CONFLICT (id) DO UPDATE). Chạy bằng superuser."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

INGESTED_AT = "2026-10-01T00:00:00+00:00"


def lit(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.isoformat()}'"
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, (dict, list)) and not isinstance(v, str):
        return (
            "'" + json.dumps(v, ensure_ascii=False, sort_keys=True).replace("'", "''") + "'::jsonb"
        )
    return "'" + str(v).replace("'", "''") + "'"


def text_array(values: list[str]) -> str:
    return "ARRAY[" + ", ".join(lit(x) for x in values) + "]::text[]" if values else "'{}'::text[]"


def upsert(table: str, cols: list[str], rows: list[list[Any]], key: str = "id") -> str:
    if not rows:
        return ""
    values = ",\n".join("  (" + ", ".join(r) + ")" for r in rows)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)
    return (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values}\n"
        f"ON CONFLICT ({key}) DO UPDATE SET {sets};\n"
    )


def _rows(items: list[dict], cols: list[str]) -> list[list[str]]:
    return [[lit(it[c]) for c in cols] for it in items]


def _setval(table: str) -> str:
    return (
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}));\n"
    )


def gateway_sql(departments: list[tuple[str, str]]) -> str:
    rows = [[lit(c), lit(n)] for c, n in departments]
    return (
        "BEGIN;\n"
        + upsert(
            "departments",
            ["code", "name"],
            rows,
            key="code",
        )
        + "COMMIT;\n"
    )


def knowledge_sql(docs: list[dict]) -> str:
    cols = [
        "id",
        "title",
        "source_path",
        "sha256",
        "department",
        "classification",
        "allowed_roles",
        "owner_sub",
        "version",
        "ingested_at",
    ]
    rows = [
        [
            lit(d["id"]),
            lit(d["title"]),
            lit(d["source_path"]),
            lit(d["sha256"]),
            lit(d["department"]),
            lit(d["classification"]),
            text_array(d["allowed_roles"]),
            lit(d["owner_sub"]),
            lit(d["version"]),
            lit(INGESTED_AT),
        ]
        for d in docs
    ]
    return "BEGIN;\n" + upsert("documents", cols, rows) + "COMMIT;\n"


def tickets_sql(data: dict[str, list[dict]]) -> str:
    tcols = [
        "id",
        "code",
        "title",
        "description",
        "status",
        "priority",
        "category",
        "requester_sub",
        "requester_dept",
        "assignee_sub",
        "assignee_dept",
        "classification",
        "created_at",
        "updated_at",
        "closed_at",
        "closed_by",
        "resolution",
    ]
    ccols = ["id", "ticket_id", "author_sub", "body", "internal", "created_at"]
    ecols = ["id", "ticket_id", "actor_sub", "action", "before", "after", "ts"]
    return (
        "BEGIN;\n"
        + upsert("tickets", tcols, _rows(data["tickets"], tcols))
        + _setval("tickets")
        + upsert("ticket_comments", ccols, _rows(data["comments"], ccols))
        + _setval("ticket_comments")
        + upsert("ticket_events", ecols, _rows(data["events"], ecols))
        + _setval("ticket_events")
        + "COMMIT;\n"
    )
