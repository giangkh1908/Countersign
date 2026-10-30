"""Adapter `DocumentRetriever`: Postgres + pgvector, vector KNN + full-text trộn bằng RRF (02 §5.3).

ACL hai lớp, cùng một nguồn là `Principal`:
  1. `WHERE` tường minh theo phòng ban / clearance / roles (trong từng nhánh vec và fts);
  2. RLS `chunk_acl`/`doc_acl` của role `kn_app`: `set_config('app.depts'|'app.clearance'|'app.roles',
     ..., true)` (transaction-local) trước truy vấn.
Chạy bằng role `kn_app` (chỉ SELECT). Embedder lỗi => suy giảm `fts_only` (vẫn qua ACL).
"""

from __future__ import annotations

import psycopg
from acme_common.ports import Principal

from ..normalize import normalize_query
from ..ports.document_retriever import DocumentRetriever
from ..ports.embedder import Embedder
from ..ports.types import EmbeddingUnavailable, RetrievalUnavailable, RetrievedChunk, SearchResult
from ._pg import connect, vec_literal

_SQL = """
WITH q AS (
  SELECT %(qv)s::vector(1024) AS qv,
         NULLIF(replace(plainto_tsquery('simple', acme.immutable_unaccent(%(qt)s::text))::text,
                        ' & ', ' | '), '')::tsquery AS qt
),
vec AS (
  SELECT id, row_number() OVER (ORDER BY dist, id) AS rnk
  FROM (
    SELECT c.id, c.embedding <=> q.qv AS dist
    FROM chunks c, q
    WHERE q.qv IS NOT NULL
      AND (c.department = 'ALL' OR c.department = ANY (%(depts)s::text[]))
      AND c.classification <= %(clr)s::int
      AND (cardinality(c.allowed_roles) = 0 OR c.allowed_roles && %(roles)s::text[])
      AND (%(dept_f)s::text IS NULL OR c.department = %(dept_f)s::text)
    ORDER BY c.embedding <=> q.qv
    LIMIT %(n_cand)s::int
  ) s
),
fts AS (
  SELECT id, row_number() OVER (ORDER BY score DESC, id) AS rnk
  FROM (
    SELECT c.id, ts_rank_cd(c.tsv, q.qt, 32) AS score
    FROM chunks c, q
    WHERE q.qt IS NOT NULL AND c.tsv @@ q.qt
      AND (c.department = 'ALL' OR c.department = ANY (%(depts)s::text[]))
      AND c.classification <= %(clr)s::int
      AND (cardinality(c.allowed_roles) = 0 OR c.allowed_roles && %(roles)s::text[])
      AND (%(dept_f)s::text IS NULL OR c.department = %(dept_f)s::text)
    ORDER BY score DESC
    LIMIT %(n_cand)s::int
  ) s
),
fused AS (
  SELECT id,
         sum(1.0 / (%(rrf_k)s::int + rnk)) AS rrf,
         min(rnk) FILTER (WHERE src = 'v') AS vec_rank,
         min(rnk) FILTER (WHERE src = 'f') AS fts_rank
  FROM (SELECT id, rnk, 'v' AS src FROM vec UNION ALL SELECT id, rnk, 'f' FROM fts) u
  GROUP BY id
)
SELECT c.id, c.document_id, c.ord, c.heading, c.content,
       c.department, c.classification, c.allowed_roles,
       d.title, d.source_path, f.rrf, f.vec_rank, f.fts_rank
FROM fused f
JOIN chunks c    ON c.id = f.id
JOIN documents d ON d.id = c.document_id
ORDER BY f.rrf DESC, c.id
LIMIT %(top_k)s::int
"""


class PgVectorHybridRetriever(DocumentRetriever):
    def __init__(
        self,
        dsn: str,
        embedder: Embedder,
        *,
        rrf_k: int = 60,
        n_cand: int | None = None,
        ef_search: int = 100,
    ) -> None:
        self._dsn = dsn
        self._embedder = embedder
        self._rrf_k = rrf_k
        self._n_cand = n_cand
        self._ef = ef_search

    async def search(
        self,
        query: str,
        principal: Principal,
        k: int,
        department_filter: str | None = None,
    ) -> SearchResult:
        text = normalize_query(query)
        qv: str | None
        try:
            qv = vec_literal((await self._embedder.embed([text]))[0])
            mode = "hybrid"
        except EmbeddingUnavailable:
            qv, mode = None, "fts_only"
        params = {
            "qv": qv,
            "qt": text,
            "depts": list(principal.dept),
            "clr": principal.clearance if principal.clearance is not None else -1,
            "roles": list(principal.roles),
            "dept_f": department_filter,
            "n_cand": self._n_cand or max(50, 5 * k),
            "rrf_k": self._rrf_k,
            "top_k": k,
        }
        try:
            async with await connect(self._dsn) as conn, conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.depts', %s, true), set_config('app.clearance', %s, true),"
                    " set_config('app.roles', %s, true),"
                    " set_config('hnsw.ef_search', %s, true),"
                    " set_config('hnsw.iterative_scan', 'relaxed_order', true)",
                    (
                        ",".join(principal.dept),
                        str(params["clr"]),
                        ",".join(principal.roles),
                        str(self._ef),
                    ),
                )
                cur = await conn.execute(_SQL, params)
                rows = await cur.fetchall()
        except (psycopg.Error, OSError, TimeoutError):
            raise RetrievalUnavailable("database") from None
        chunks = [
            RetrievedChunk(
                chunk_id=r[0],
                doc_id=str(r[1]),
                ord=r[2],
                heading=r[3],
                content=r[4],
                department=r[5],
                classification=r[6],
                allowed_roles=tuple(r[7]),
                title=r[8],
                source=f"{r[9]}#{r[2]}",
                score=float(r[10]),
                vec_rank=r[11],
                fts_rank=r[12],
            )
            for r in rows
        ]
        return SearchResult(chunks, mode)
