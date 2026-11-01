"""Adapter `json_log` cho port `EventSink`.
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import logging

from ..ports.event_sink import EventRecord, EventSink


class JsonLogEventSink(EventSink):
    """Mỗi event là một dòng log JSON (logger `acme.events`); `log.JsonFormatter` che khoá nhạy cảm."""

    def __init__(self, logger_name: str = "acme.events") -> None:
        self._logger = logging.getLogger(logger_name)

    def append(self, record: EventRecord, sync: bool = False) -> None:
        self._logger.info(
            str(record.get("event", "event")), extra={"fields": {**record, "sync": sync}}
        )

    async def flush(self, timeout_s: float = 5.0) -> None:
        for h in self._logger.handlers + logging.getLogger().handlers:
            h.flush()
