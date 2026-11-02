"""Sinh `documents.jsonl` (metadata ACL) cho corpus luật từ selection.json + manifest.json.

    uv run python -m data.vbpl.metadata [--dir data/raw/vbpl]

Ánh xạ nhóm -> ACL là giả lập có chủ đích (data/SOURCES.md §1): luật công khai nhưng gán phòng ban
để thử phân quyền. Id tất định (uuid5 theo source_path) nên chạy lại ra cùng kết quả.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

HERE = Path(__file__).parent
NAMESPACE_VBPL = uuid.UUID("5b0c3f0e-6d3a-4f8e-9a52-7c1e2d9b4a10")
KIND = "van_ban_phap_luat"

# nhóm -> (department, classification); thang classification 0..3 theo contracts §3.2
GROUP_ACL: dict[str, tuple[str, int]] = {
    "hr": ("HR", 1),
    "it": ("IT", 1),
    "finance": ("ALL", 0),
    "legal": ("ALL", 0),
}


def slug_of(doc_num: str) -> str:
    return doc_num.replace("/", "-").lower()


def build_metadata(raw_dir: Path, selection: list[dict] | None = None) -> list[dict]:
    items = selection or json.loads((HERE / "selection.json").read_text(encoding="utf-8"))
    manifest_path = raw_dir / "manifest.json"
    known: set[str] | None = None
    if manifest_path.is_file():
        known = {m["doc_num"] for m in json.loads(manifest_path.read_text(encoding="utf-8"))}
    rows: list[dict] = []
    for it in items:
        group = it["group"]
        if group not in GROUP_ACL:
            raise ValueError(f"nhóm lạ {group!r} ở {it['doc_num']}")
        if known is not None and it["doc_num"] not in known:
            raise ValueError(f"{it['doc_num']} có trong selection nhưng không có trong manifest")
        dept, cls = GROUP_ACL[group]
        source_path = f"{slug_of(it['doc_num'])}.json"
        rows.append(
            {
                "id": str(uuid.uuid5(NAMESPACE_VBPL, source_path)),
                "source_path": source_path,
                "title": it["title"],
                "doc_num": it["doc_num"],
                "kind": KIND,
                "department": dept,
                "classification": cls,
                "allowed_roles": [],
                "sha256": hashlib.sha256((raw_dir / source_path).read_bytes()).hexdigest(),
                "owner_sub": None,
                "version": 1,
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/raw/vbpl")
    args = ap.parse_args()
    raw = Path(args.dir)
    rows = build_metadata(raw)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    (raw / "documents.jsonl").write_text(body, encoding="utf-8", newline="")
    print(f"documents.jsonl: {len(rows)} văn bản -> {raw / 'documents.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
