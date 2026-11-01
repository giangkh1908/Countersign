"""Port `EventSink`: `append(record, sync=False)`, `flush()` (gộp Usage/Audit/ToolAudit sink).

Adapter v1 dự kiến: `postgres`, `json_log`.
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any

EventRecord = Mapping[str, Any]


class EventSink(abc.ABC):
    @abc.abstractmethod
    def append(self, record: EventRecord, sync: bool = False) -> None:
        """`sync=False`: không chặn (đưa vào batch). `sync=True`: ghi ngay (audit)."""

    @abc.abstractmethod
    async def flush(self, timeout_s: float = 5.0) -> None:
        """Đẩy phần còn lại của batch (shutdown)."""
