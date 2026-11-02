"""Adapter `postgres` cho port `DeliveryLog` (psycopg 3 async, role `nt_app`, bảng `report_deliveries`).

Mỗi lời gọi một câu lệnh autocommit. `UNIQUE(intent_id)` là chốt chặn gửi đúp độc lập với Redis.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from acme_common.ports import DuplicateIntent
from psycopg import errors as pgerr

from ..ports import DeliveryLog, DeliveryLogUnavailable, DeliveryRecord, DeliveryStatus

log = logging.getLogger("acme.mcp_notify.postgres")


class PostgresDeliveryLog(DeliveryLog):
    def __init__(self, dsn: str, *, connect_timeout_s: int = 5) -> None:
        self._dsn = dsn
        self._timeout = connect_timeout_s

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        try:
            return await psycopg.AsyncConnection.connect(
                self._dsn, connect_timeout=self._timeout, autocommit=True
            )
        except psycopg.Error:
            raise DeliveryLogUnavailable("connect", not_written=True) from None

    async def begin(
        self, intent_id: str, channel: str, text_sha256: str, actor_sub: str, approval_jti: str
    ) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT INTO report_deliveries (intent_id, channel, text_sha256, actor_sub, approval_jti, status) "
                "VALUES (%s, %s, %s, %s, %s, 'sending')",
                (intent_id, channel, text_sha256, actor_sub, approval_jti),
            )
        except pgerr.UniqueViolation:
            raise DuplicateIntent from None
        except psycopg.Error:
            raise DeliveryLogUnavailable("insert") from None
        finally:
            await conn.close()

    async def finish(self, intent_id: str, status: DeliveryStatus, detail: str = "") -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                "UPDATE report_deliveries SET status = %s, detail = %s, updated_at = now() "
                "WHERE intent_id = %s AND status = 'sending'",
                (status, detail[:64], intent_id),
            )
        except psycopg.Error:
            raise DeliveryLogUnavailable("update") from None
        finally:
            await conn.close()

    async def find(self, intent_id: str) -> DeliveryRecord | None:
        conn = await self._connect()
        try:
            cur = await conn.execute(
                "SELECT intent_id::text, channel, text_sha256, status, detail "
                "FROM report_deliveries WHERE intent_id = %s",
                (intent_id,),
            )
            row = await cur.fetchone()
        except psycopg.Error:
            raise DeliveryLogUnavailable("select") from None
        finally:
            await conn.close()
        if row is None:
            return None
        return DeliveryRecord(row[0], row[1], row[2], row[3], row[4])
