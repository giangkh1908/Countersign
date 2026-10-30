"""Adapter `postgres` cho port `EventSink`.
Milestone: M1/M2.
Tài liệu: docs/design/00-contracts.md §9.2.
"""

from __future__ import annotations

from ..ports.event_sink import EventRecord, EventSink


class PostgresEventSink(EventSink):
    """Stub: hiện thực ở M2 (batch writer, hash-chain HMAC, sync cùng transaction)."""

    def append(self, record: EventRecord, sync: bool = False) -> None:
        raise NotImplementedError("postgres event sink: M2")

    async def flush(self, timeout_s: float = 5.0) -> None:
        raise NotImplementedError("postgres event sink: M2")
