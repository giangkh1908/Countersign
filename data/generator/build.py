"""Ghép các module sinh dữ liệu và ghi đầu ra tất định (không timestamp, không đường dẫn máy)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import sqlout
from .docs import build_docs
from .tickets import build_tickets
from .users import DEFAULT_REALM, REPO_ROOT, load_users

SEED = 20261028
GENERATOR_VERSION = "1.0"
DEFAULT_OUT = REPO_ROOT / "data" / "generated"
# (code, tên, ngân sách tháng micro-USD) — contracts §3.1 / 04 §7.3
DEPARTMENTS = [
    ("SALES", "Kinh doanh", 30_000_000),
    ("ENG", "Kỹ thuật", 60_000_000),
    ("HR", "Nhân sự", 10_000_000),
    ("CS", "Chăm sóc khách hàng", 40_000_000),
    ("IT", "Công nghệ thông tin", 20_000_000),
    ("EVAL", "Đánh giá (kỹ thuật)", 160_000_000),
]


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)  # bytes: không đổi xuống dòng theo hệ điều hành
    return hashlib.sha256(data).hexdigest()


def build(
    out: Path = DEFAULT_OUT,
    seed: int = SEED,
    realm_path: Path = DEFAULT_REALM,
    sub_map: dict[str, str] | None = None,
) -> dict:
    users = load_users(realm_path, sub_map)
    docs = build_docs(users)
    tk = build_tickets(users, seed)

    if out.exists():
        shutil.rmtree(out)
    files: dict[str, str] = {}
    for d in docs:
        files[d["source_path"]] = _write(out / d["source_path"], d["content"])
    meta = [{k: v for k, v in d.items() if k != "content"} for d in docs]
    files["documents.jsonl"] = _write(
        out / "documents.jsonl",
        "".join(json.dumps(m, ensure_ascii=False, sort_keys=True) + "\n" for m in meta),
    )
    files["users.json"] = _write(
        out / "users.json",
        json.dumps(
            [
                {
                    "sub": u.sub,
                    "username": u.username,
                    "employee_id": u.employee_id,
                    "departments": list(u.departments),
                    "clearance": u.clearance,
                    "roles": list(u.roles),
                }
                for u in users
            ],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    files["sql/gateway.sql"] = _write(out / "sql" / "gateway.sql", sqlout.gateway_sql(DEPARTMENTS))
    files["sql/knowledge.sql"] = _write(out / "sql" / "knowledge.sql", sqlout.knowledge_sql(docs))
    files["sql/tickets.sql"] = _write(out / "sql" / "tickets.sql", sqlout.tickets_sql(tk))

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "counts": {
            "users": len(users),
            "documents": len(docs),
            "tickets": len(tk["tickets"]),
            "ticket_comments": len(tk["comments"]),
            "ticket_events": len(tk["events"]),
            "departments": len(DEPARTMENTS),
        },
        "synthetic_pii_tickets": [t["code"] for t in tk["tickets"] if t["synthetic_pii"]],
        "files": dict(sorted(files.items())),
    }
    _write(out / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest
