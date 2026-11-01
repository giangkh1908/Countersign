"""Tiện ích dùng chung của hai adapter Postgres/pgvector (retriever và indexer)."""

from __future__ import annotations

import psycopg


def vec_literal(v: list[float]) -> str:
    """Dạng văn bản của kiểu vector: `[0.1,0.2,...]` (truyền như tham số text rồi `::vector`)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


async def connect(dsn: str, *, connect_timeout_s: int = 3) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(dsn, connect_timeout=connect_timeout_s)
