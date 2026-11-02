"""Tiện ích dùng chung của hai adapter Postgres/pgvector (retriever và indexer)."""

from __future__ import annotations

import psycopg


def vec_literal(v: list[float]) -> str:
    """Dạng văn bản của kiểu vector: `[0.1,0.2,...]` (truyền như tham số text rồi `::vector`)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


async def connect(dsn: str, *, connect_timeout_s: int = 3) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(dsn, connect_timeout=connect_timeout_s)


async def embedding_dim(conn: psycopg.AsyncConnection) -> int | None:
    """Số chiều của cột `chunks.embedding` (với kiểu vector, `atttypmod` chính là số chiều)."""
    cur = await conn.execute(
        "SELECT atttypmod FROM pg_attribute"
        " WHERE attrelid = 'public.chunks'::regclass AND attname = 'embedding' AND NOT attisdropped"
    )
    row = await cur.fetchone()
    return row[0] if row and row[0] > 0 else None


async def read_index_meta(conn: psycopg.AsyncConnection) -> dict[str, str]:
    cur = await conn.execute("SELECT key, value FROM index_meta")
    return {k: v for k, v in await cur.fetchall()}
