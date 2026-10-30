"""Adapter `postgres` cho port `EventSink` (psycopg 3).

Định tuyến theo `record["event"]`:
- `usage_event` -> bảng `usage_events` (batch `executemany`, ghi ở `flush()` hoặc khi buffer đầy);
- `audit_log` / `tool_audit` -> hash-chain HMAC (`acme_common.audit.pg`). `sync=True` ghi ngay
  (một transaction riêng); `sync=False` vào buffer và ghi ở `flush()`.
Một connection đồng bộ + khoá luồng: `append` của port là hàm đồng bộ; nơi gọi trong event loop nên
chạy `await asyncio.to_thread(sink.append, rec, True)` (ToolInvoker làm sẵn). Lỗi DB: buffer giữ lại
(giới hạn `max_buffer`, vượt thì bỏ bản cũ nhất và đếm `dropped`); `sync=True` raise cho caller.
Milestone: M1. Tài liệu: docs/design/00-contracts.md §3.1, §3.6, §9.2.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Mapping
from typing import Any

import psycopg

from ..audit import AuditKeyring
from ..audit.pg import AUDIT_TABLES, append_audit_sync
from ..ports.event_sink import EventRecord, EventSink

log = logging.getLogger("acme.postgres_event_sink")

_USAGE_COLUMNS = (
    "ts", "request_id", "key_id", "department", "end_user_sub", "alias", "provider", "model",
    "input_tokens", "output_tokens", "cached_input_tokens", "cost_micro_usd", "latency_ms",
    "ttft_ms", "gateway_overhead_ms", "sidecar_ms", "cache", "fallback_count", "route_reason",
    "pii_entities", "guard_score", "status_code", "error_code",
)  # fmt: skip
_USAGE_REQUIRED = ("request_id", "key_id", "department", "alias", "status_code")


class PostgresEventSink(EventSink):
    def __init__(
        self,
        dsn: str,
        keyring: AuditKeyring | None = None,
        *,
        batch_size: int = 100,
        max_buffer: int = 10_000,
        connect_timeout_s: int = 5,
    ) -> None:
        self._dsn = dsn
        self._keyring = keyring
        self._batch_size = batch_size
        self._connect_timeout_s = connect_timeout_s
        self._usage: deque[dict[str, Any]] = deque(maxlen=max_buffer)
        self._audit: deque[tuple[str, dict[str, Any]]] = deque(maxlen=max_buffer)
        self._lock = threading.RLock()
        self._conn: psycopg.Connection[Any] | None = None
        self.dropped = 0
        self.write_failures = 0

    # --- connection ---
    def _connection(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self._dsn, autocommit=True, connect_timeout=self._connect_timeout_s
            )
        return self._conn

    def _drop_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 - đóng connection hỏng, bỏ qua lỗi phụ
                log.debug("close failed", exc_info=True)
            self._conn = None

    # --- port ---
    def append(self, record: EventRecord, sync: bool = False) -> None:
        event = record.get("event")
        if event == "usage_event":
            self._append_usage(record)
        elif event in AUDIT_TABLES:
            self._append_audit(str(event), record, sync)
        else:
            raise ValueError(f"postgres event sink: unsupported event {event!r}")

    def _append_usage(self, record: EventRecord) -> None:
        for f in _USAGE_REQUIRED:
            if record.get(f) is None:
                raise ValueError(f"usage_event missing {f!r}")
        with self._lock:
            if len(self._usage) == self._usage.maxlen:
                self.dropped += 1
            self._usage.append({k: record[k] for k in _USAGE_COLUMNS if k in record})
            full = len(self._usage) >= self._batch_size
        if full:
            self._flush_usage()

    def _append_audit(self, table: str, record: EventRecord, sync: bool) -> None:
        if self._keyring is None:
            raise RuntimeError("audit event requires AUDIT_HMAC_KEY (keyring)")
        item = {k: v for k, v in record.items() if k != "event"}
        if not sync:
            with self._lock:
                if len(self._audit) == self._audit.maxlen:
                    self.dropped += 1
                self._audit.append((table, item))
            return
        with self._lock:
            try:
                conn = self._connection()
                with conn.transaction():
                    append_audit_sync(conn, table, item, self._keyring)
            except Exception:
                self.write_failures += 1
                self._drop_conn()
                raise

    async def flush(self, timeout_s: float = 5.0) -> None:
        import asyncio

        try:
            await asyncio.wait_for(asyncio.to_thread(self.flush_sync), timeout_s)
        except TimeoutError:
            log.warning("event sink flush timed out")

    # --- batch ---
    def flush_sync(self) -> None:
        self._flush_usage()
        self._flush_audit()

    def _flush_usage(self) -> None:
        with self._lock:
            if not self._usage:
                return
            batch = list(self._usage)
            self._usage.clear()
            try:
                conn = self._connection()
                groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
                for r in batch:
                    groups.setdefault(tuple(r), []).append(r)
                with conn.transaction():
                    for cols, rows in groups.items():
                        sql = (
                            f"INSERT INTO usage_events ({', '.join(cols)}) "
                            f"VALUES ({', '.join(['%s'] * len(cols))})"
                        )
                        with conn.cursor() as cur:
                            cur.executemany(sql, [[r[c] for c in cols] for r in rows])  # type: ignore[arg-type]
            except Exception:
                self.write_failures += 1
                self._drop_conn()
                self._usage.extendleft(reversed(batch))  # giữ lại để thử lần sau
                log.warning("usage_events batch write failed; kept in buffer", exc_info=True)

    def _flush_audit(self) -> None:
        with self._lock:
            while self._audit:
                table, item = self._audit[0]
                assert self._keyring is not None
                try:
                    conn = self._connection()
                    with conn.transaction():
                        append_audit_sync(conn, table, item, self._keyring)
                except Exception:
                    self.write_failures += 1
                    self._drop_conn()
                    log.warning("audit batch write failed; kept in buffer", exc_info=True)
                    return
                self._audit.popleft()
