"""Adapter `DocumentIndexer`: ghi `documents` + `chunks` bằng role `kn_ingest` (INSERT/UPDATE/DELETE).

Một transaction cho mỗi tài liệu. `tsv` do Postgres sinh tự động. Idempotent theo `sha256`.
"""

from __future__ import annotations

import psycopg

from ..ports.document_indexer import DocumentIndexer, IndexedChunk
from ..ports.types import DocumentMeta, RetrievalUnavailable
from ._pg import connect, vec_literal


class PgVectorIndexer(DocumentIndexer):
    def __init__(self, dsn: str, *, dim: int = 1024) -> None:
        self._dsn = dsn
        self._dim = dim

    async def is_current(self, meta: DocumentMeta) -> bool:
        try:
            async with await connect(self._dsn) as conn:
                cur = await conn.execute(
                    "SELECT d.sha256, d.department, d.classification, d.allowed_roles,"
                    " (SELECT count(*) FROM chunks c WHERE c.document_id = d.id)"
                    " FROM documents d WHERE d.id = %s",
                    (meta.id,),
                )
                row = await cur.fetchone()
        except (psycopg.Error, OSError, TimeoutError):
            raise RetrievalUnavailable("database") from None
        return bool(
            row
            and row[0].strip() == meta.sha256
            and row[1] == meta.department
            and row[2] == meta.classification
            and sorted(row[3]) == sorted(meta.allowed_roles)
            and row[4] > 0
        )

    async def replace(self, meta: DocumentMeta, chunks: list[IndexedChunk]) -> None:
        for c in chunks:
            if len(c.embedding) != self._dim:
                raise ValueError("embedding dimension mismatch")
        roles = list(meta.allowed_roles)
        try:
            async with await connect(self._dsn) as conn, conn.transaction():
                cur = await conn.execute(
                    "SELECT sha256, version FROM documents WHERE id = %s FOR UPDATE", (meta.id,)
                )
                old = await cur.fetchone()
                version = (old[1] + (1 if old[0].strip() != meta.sha256 else 0)) if old else 1
                await conn.execute(
                    "INSERT INTO documents (id, title, source_path, sha256, department,"
                    " classification, allowed_roles, owner_sub, version, ingested_at)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s::text[],%s,%s, now())"
                    " ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title,"
                    " source_path=EXCLUDED.source_path, sha256=EXCLUDED.sha256,"
                    " department=EXCLUDED.department, classification=EXCLUDED.classification,"
                    " allowed_roles=EXCLUDED.allowed_roles, owner_sub=EXCLUDED.owner_sub,"
                    " version=EXCLUDED.version, ingested_at=now()",
                    (
                        meta.id,
                        meta.title,
                        meta.source_path,
                        meta.sha256,
                        meta.department,
                        meta.classification,
                        roles,
                        meta.owner_sub,
                        version,
                    ),
                )
                await conn.execute("DELETE FROM chunks WHERE document_id = %s", (meta.id,))
                async with conn.cursor() as cur2:
                    await cur2.executemany(
                        "INSERT INTO chunks (document_id, ord, heading, content, n_tokens,"
                        " department, classification, allowed_roles, embedding)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s::text[],%s::vector)",
                        [
                            (
                                meta.id,
                                c.chunk.ord,
                                c.chunk.heading,
                                c.chunk.content,
                                c.chunk.n_tokens,
                                meta.department,
                                meta.classification,
                                roles,
                                vec_literal(c.embedding),
                            )
                            for c in chunks
                        ],
                    )
        except (psycopg.Error, OSError, TimeoutError):
            raise RetrievalUnavailable("database") from None
