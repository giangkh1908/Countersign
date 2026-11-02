"""Adapter `DocumentRetriever`: Postgres + pgvector, vector KNN + Postgres FTS trộn bằng RRF.

Nhánh full-text là Postgres FTS (`ts_rank_cd`), KHÔNG phải BM25. Hai công tắc `use_vector`/`use_fts`
cho ra các cấu hình vector_only / fts_only / hybrid; `fts_mode` chọn cột `tsv` hay `tsv_seg`.

ACL hai lớp, cùng một nguồn là `Principal`:
  1. `WHERE` tường minh theo phòng ban / clearance / roles (trong từng nhánh vec và fts);
  2. RLS `chunk_acl`/`doc_acl` của role `kn_app`: `set_config('app.depts'|'app.clearance'|'app.roles',
     ..., true)` (transaction-local) trước truy vấn.
Chạy bằng role `kn_app` (chỉ SELECT). Embedder lỗi => suy giảm `fts_only` nếu nhánh FTS bật (vẫn qua
ACL), ngược lại `RetrievalUnavailable`.
"""

from __future__ import annotations

import logging

import psycopg
from acme_common.ports import Principal

from ..ports.document_retriever import DocumentRetriever
from ..ports.embedder import Embedder
from ..ports.text_segmenter import TextSegmenter
from ..ports.types import (
    EmbeddingUnavailable,
    IndexConfigError,
    RetrievalUnavailable,
    RetrievedChunk,
    SearchResult,
)
from ..services.fts_query import strip_stopwords
from ..services.normalize import normalize_query
from ._pg import connect, embedding_dim, read_index_meta, vec_literal
from .segmenter_none import NoSegmenter

log = logging.getLogger("acme.docs.retriever")

# DOCS_FTS_MODE -> cột tsvector (khoá cố định, không nhận chuỗi từ người dùng)
_FTS_COLUMNS = {"unaccent": "tsv", "segmented": "tsv_seg"}
# DOCS_FTS_RANK -> hàm xếp hạng (khoá cố định)
_FTS_RANKS = {"cd": "ts_rank_cd", "rank": "ts_rank"}
# Thử nghiệm DOCS_FTS_TITLE: ghép tiêu đề văn bản (trọng số A) vào tsv ngay lúc truy vấn, không đổi
# migration; mất khả năng dùng chỉ mục GIN của tsv (chấp nhận được ở quy mô hàng nghìn chunk).
_TITLE_DOC = "(setweight(to_tsvector('simple', acme.immutable_unaccent(d.title)), 'A') || c.tsv)"

_SQL = """
WITH q AS (
  SELECT %(qv)s::vector AS qv,
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
    SELECT c.id, {rank_fn}({fts_doc}, q.qt, 32) AS score
    FROM chunks c{fts_from}, q
    WHERE q.qt IS NOT NULL AND {fts_doc} @@ q.qt
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
         sum(CASE WHEN src = 'f' THEN %(w_fts)s::float8 ELSE 1.0 END
             / (%(rrf_k)s::int + rnk)) AS rrf,
         min(rnk) FILTER (WHERE src = 'v') AS vec_rank,
         min(rnk) FILTER (WHERE src = 'f') AS fts_rank
  FROM (SELECT id, rnk, 'v' AS src FROM vec UNION ALL SELECT id, rnk, 'f' FROM fts) u
  GROUP BY id
)
SELECT c.id, c.document_id, c.ord, c.heading, c.content,
       c.department, c.classification, c.allowed_roles,
       d.title, d.source_path, f.rrf, f.vec_rank, f.fts_rank,
       d.doc_num, c.article, c.clause, c.chapter, c.char_start, c.char_end
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
        use_vector: bool = True,
        use_fts: bool = True,
        fts_mode: str = "unaccent",
        rrf_weight_fts: float = 1.0,
        fts_stopwords: bool = False,
        fts_rank: str = "cd",
        fts_title: bool = False,
        segmenter: TextSegmenter | None = None,
    ) -> None:
        if not (use_vector or use_fts):
            raise ValueError("at least one of use_vector/use_fts must be enabled")
        if fts_mode not in _FTS_COLUMNS:
            raise ValueError(f"fts_mode must be one of {sorted(_FTS_COLUMNS)}")
        if fts_rank not in _FTS_RANKS:
            raise ValueError(f"fts_rank must be one of {sorted(_FTS_RANKS)}")
        if rrf_weight_fts < 0:
            raise ValueError("rrf_weight_fts must be >= 0")
        if fts_title and fts_mode != "unaccent":
            raise ValueError("fts_title chỉ hỗ trợ fts_mode=unaccent")
        self._dsn = dsn
        self._embedder = embedder
        self._rrf_k = rrf_k
        self._n_cand = n_cand
        self._ef = ef_search
        self._use_vector = use_vector
        self._use_fts = use_fts
        self._segmenter = segmenter or NoSegmenter()
        # "segmented" truy vấn cột tsv_seg bằng term đã qua cùng bộ tách từ lúc ingest
        self._segment_query = fts_mode == "segmented"
        self._w_fts = rrf_weight_fts
        self._fts_stopwords = fts_stopwords
        fts_doc = _TITLE_DOC if fts_title else f"c.{_FTS_COLUMNS[fts_mode]}"
        self._sql = (
            _SQL.replace("{fts_doc}", fts_doc)
            .replace("{fts_from}", " JOIN documents d ON d.id = c.document_id" if fts_title else "")
            .replace("{rank_fn}", _FTS_RANKS[fts_rank])
        )

    async def verify_schema(
        self, expected_dim: int, *, embed_model: str | None = None, strict_meta: bool = False
    ) -> None:
        try:
            async with await connect(self._dsn) as conn:
                dim = await embedding_dim(conn)
                meta = await read_index_meta(conn)
        except (psycopg.Error, OSError, TimeoutError):
            raise RetrievalUnavailable("database") from None
        if dim != expected_dim:
            raise IndexConfigError(
                f"chunks.embedding là vector({dim}) nhưng DOCS_EMBED_DIM={expected_dim}; "
                "đồng bộ EMBED_DIM và chạy lại knowledge-migrate"
            )
        stored = meta.get("embed_model")
        if embed_model and stored and stored != embed_model:
            msg = f"chỉ mục dựng bằng embed_model={stored!r}, cấu hình hiện tại {embed_model!r}"
            if strict_meta:
                raise IndexConfigError(msg)
            log.warning(msg)

    async def search(
        self,
        query: str,
        principal: Principal,
        k: int,
        department_filter: str | None = None,
    ) -> SearchResult:
        text = normalize_query(query)
        qv: str | None = None
        use_fts = self._use_fts
        if self._use_vector:
            try:
                qv = vec_literal((await self._embedder.embed([text]))[0])
            except EmbeddingUnavailable:
                if not use_fts:
                    raise RetrievalUnavailable("embedding") from None
        mode = "hybrid" if (qv and use_fts) else "vector_only" if qv else "fts_only"
        qt = None
        if use_fts:
            qt = strip_stopwords(text) if self._fts_stopwords else text
            if self._segment_query:
                qt = self._segmenter.segment(qt)
        params = {
            "qv": qv,
            "qt": qt,
            "depts": list(principal.dept),
            "clr": principal.clearance if principal.clearance is not None else -1,
            "roles": list(principal.roles),
            "dept_f": department_filter,
            "n_cand": self._n_cand or max(50, 5 * k),
            "rrf_k": self._rrf_k,
            "w_fts": self._w_fts,
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
                cur = await conn.execute(self._sql, params)
                rows = await cur.fetchall()
        except (psycopg.Error, OSError, TimeoutError):
            raise RetrievalUnavailable("database") from None
        return SearchResult([row_to_chunk(r) for r in rows], mode)


def row_to_chunk(r: tuple) -> RetrievedChunk:  # type: ignore[type-arg]
    """Hàng kết quả (thứ tự cột của `_SQL` và của adapter tra trực tiếp) -> `RetrievedChunk`."""
    return RetrievedChunk(
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
        doc_num=r[13],
        article=r[14],
        clause=r[15],
        chapter=r[16],
        char_start=r[17],
        char_end=r[18],
    )
