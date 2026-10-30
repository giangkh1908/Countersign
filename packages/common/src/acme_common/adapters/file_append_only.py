"""Adapter `file_append_only` cho port `AnchorStore`. Dev: AUDIT_ANCHOR_DIR.
Milestone: M2.
Tài liệu: docs/design/00-contracts.md §9.2.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ..ports.anchor_store import AnchorStore, AuditAnchor


class FileAppendOnlyAnchorStore(AnchorStore):
    """JSONL theo ngày (`anchors-YYYY-MM-DD.jsonl`), mở `O_APPEND`, fsync sau mỗi bản ghi.

    Không bao giờ ghi đè hay xoá; host đặt thêm `chattr +a` / volume chỉ-ghi-thêm (01 §13.4).
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)

    def _put(self, anchor: AuditAnchor) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"anchors-{anchor.ts.date().isoformat()}.jsonl"
        line = json.dumps(anchor.to_dict(), sort_keys=True, ensure_ascii=False) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, line.encode("utf8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def _all(self) -> list[AuditAnchor]:
        if not self._dir.is_dir():
            return []
        out: list[AuditAnchor] = []
        for path in sorted(self._dir.glob("anchors-*.jsonl")):
            for line in path.read_text(encoding="utf8").splitlines():
                if line.strip():
                    out.append(AuditAnchor.from_dict(json.loads(line)))
        return out

    async def put(self, anchor: AuditAnchor) -> None:
        await asyncio.to_thread(self._put, anchor)

    async def latest(self) -> AuditAnchor | None:
        anchors = await asyncio.to_thread(self._all)
        return max(anchors, key=lambda a: a.last_id, default=None)

    async def list_since(self, since_id: int) -> list[AuditAnchor]:
        anchors = await asyncio.to_thread(self._all)
        return sorted((a for a in anchors if a.last_id > since_id), key=lambda a: a.last_id)
