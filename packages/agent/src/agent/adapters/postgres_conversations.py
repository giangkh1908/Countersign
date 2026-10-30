"""Adapter `postgres` của `ConversationRepository` (bảng `conversations`, contracts §3.5).

Chưa có test với Postgres thật trong M1 (không chạy DB ở bước này); logic SQL tối thiểu.
"""

from __future__ import annotations

import uuid

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ..ports.conversations import Conversation, ConversationRepository

_COLS = "thread_id::text AS thread_id, user_sub, title, created_at, last_active_at"


def _row(r: dict) -> Conversation:
    return Conversation(
        r["thread_id"], r["user_sub"], r["title"], r["created_at"], r["last_active_at"]
    )


class PostgresConversationRepository(ConversationRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(self, user_sub: str, title: str | None) -> Conversation:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"INSERT INTO conversations (thread_id, user_sub, title) VALUES (%s, %s, %s) RETURNING {_COLS}",
                (uuid.uuid4(), user_sub, title),
            )
            return _row(await cur.fetchone())  # type: ignore[arg-type]

    async def get(self, thread_id: str, user_sub: str) -> Conversation | None:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_COLS} FROM conversations WHERE thread_id = %s AND user_sub = %s AND deleted_at IS NULL",
                (thread_id, user_sub),
            )
            r = await cur.fetchone()
            return _row(r) if r else None

    async def list(self, user_sub: str, limit: int) -> list[Conversation]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_COLS} FROM conversations WHERE user_sub = %s AND deleted_at IS NULL "
                "ORDER BY last_active_at DESC LIMIT %s",
                (user_sub, limit),
            )
            return [_row(r) for r in await cur.fetchall()]

    async def touch(self, thread_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE conversations SET last_active_at = now() WHERE thread_id = %s", (thread_id,)
            )

    async def mark_deleted(self, thread_id: str, user_sub: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE conversations SET deleted_at = now() WHERE thread_id = %s AND user_sub = %s "
                "AND deleted_at IS NULL",
                (thread_id, user_sub),
            )
            return cur.rowcount > 0
