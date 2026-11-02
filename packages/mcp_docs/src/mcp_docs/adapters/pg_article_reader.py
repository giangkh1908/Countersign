"""Adapter `ArticleReader`: đọc chunk theo (số hiệu, Điều) bằng role `kn_app`, cùng ACL hai lớp.

Mọi truy vấn có `WHERE` tường minh theo phòng ban / clearance / roles VÀ chạy sau `set_config`
transaction-local để RLS `chunk_acl`/`doc_acl` cùng lọc. Không có đường đọc nào bỏ qua quyền.
"""

from __future__ import annotations

import psycopg
from acme_common.ports import Principal

from ..ports.article_reader import ArticleReader
from ..ports.types import Ref, RetrievalUnavailable, RetrievedChunk
from ..refs import fold
from ._pg import connect
from .pgvector_hybrid import row_to_chunk

_ACL = """
      (c.department = 'ALL' OR c.department = ANY (%(depts)s::text[]))
  AND c.classification <= %(clr)s::int
  AND (cardinality(c.allowed_roles) = 0 OR c.allowed_roles && %(roles)s::text[])
"""

_READ = (
    """
SELECT c.id, c.document_id, c.ord, c.heading, c.content,
       c.department, c.classification, c.allowed_roles,
       d.title, d.source_path, 1.0, NULL::int, NULL::int,
       d.doc_num, c.article, c.clause, c.chapter, c.char_start, c.char_end
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE upper(d.doc_num) = upper(%(doc_num)s::text) AND lower(c.article) = lower(%(article)s::text)
  AND """
    + _ACL
    + """
ORDER BY c.ord
"""
)

_FIND = """
SELECT d.doc_num, d.title
FROM documents d
WHERE d.doc_num IS NOT NULL
  AND acme.immutable_unaccent(lower(d.title)) LIKE '%%' || %(hint)s::text || '%%'
  AND (d.department = 'ALL' OR d.department = ANY (%(depts)s::text[]))
  AND d.classification <= %(clr)s::int
  AND (cardinality(d.allowed_roles) = 0 OR d.allowed_roles && %(roles)s::text[])
ORDER BY d.doc_num
"""


class PgArticleReader(ArticleReader):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _query(
        self, sql: str, params_list: list[dict], principal: Principal
    ) -> list[list[tuple]]:  # type: ignore[type-arg]
        clr = principal.clearance if principal.clearance is not None else -1
        acl = {"depts": list(principal.dept), "clr": clr, "roles": list(principal.roles)}
        try:
            async with await connect(self._dsn) as conn, conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.depts', %s, true), set_config('app.clearance', %s, true),"
                    " set_config('app.roles', %s, true)",
                    (",".join(principal.dept), str(clr), ",".join(principal.roles)),
                )
                out = []
                for p in params_list:
                    cur = await conn.execute(sql, {**p, **acl})
                    out.append(await cur.fetchall())
                return out
        except (psycopg.Error, OSError, TimeoutError):
            raise RetrievalUnavailable("database") from None

    async def read(self, refs: list[Ref], principal: Principal) -> list[RetrievedChunk]:
        wanted = [
            {"doc_num": r.doc_num, "article": r.article} for r in refs if r.doc_num and r.article
        ]
        if not wanted:
            return []
        seen: set[int] = set()
        out: list[RetrievedChunk] = []
        for rows in await self._query(_READ, wanted, principal):
            for row in rows:
                if row[0] not in seen:
                    seen.add(row[0])
                    out.append(row_to_chunk(row))
        return out

    async def find_documents(self, hint: str, principal: Principal) -> list[tuple[str, str]]:
        needle = fold(hint).strip()
        if not needle:
            return []
        like = needle.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        rows = (await self._query(_FIND, [{"hint": like}], principal))[0]
        found = [(r[0], r[1]) for r in rows]
        exact = [f for f in found if fold(f[1]).strip() == needle]
        return exact or found
