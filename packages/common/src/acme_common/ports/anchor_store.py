"""Port `AnchorStore`: `put(anchor)`, `latest()`.

Adapter v1 dự kiến: `file_append_only` (dev); sau: `s3_object_lock`.
Milestone: M2.
Tài liệu: docs/design/00-contracts.md §9.2, D14.
"""

from __future__ import annotations

import abc
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class AuditAnchor:
    """Bản ghi neo hash-chain (contracts §3.1): `sig` là HMAC của các trường còn lại."""

    chain: str
    last_id: int
    last_hash: str
    ts: datetime
    hmac_kid: str
    sig: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditAnchor:
        return cls(
            chain=d["chain"],
            last_id=int(d["last_id"]),
            last_hash=d["last_hash"],
            ts=datetime.fromisoformat(d["ts"]),
            hmac_kid=d["hmac_kid"],
            sig=d["sig"],
        )


class AnchorStore(abc.ABC):
    @abc.abstractmethod
    async def put(self, anchor: AuditAnchor) -> None:
        """Ghi vào kho append-only ngoài DB."""

    @abc.abstractmethod
    async def latest(self) -> AuditAnchor | None:
        """Anchor có `last_id` lớn nhất, hoặc None."""

    @abc.abstractmethod
    async def list_since(self, since_id: int) -> list[AuditAnchor]:
        """Mọi anchor có `last_id > since_id`, tăng dần (verify_audit --anchors)."""
