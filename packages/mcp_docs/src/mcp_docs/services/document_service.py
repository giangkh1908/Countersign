"""`DocumentService`: nơi duy nhất chứa nghiệp vụ search (02 §5.0). Chỉ phụ thuộc port.

Chuỗi: NFC query -> retriever -> reranker -> kiểm lại ACL từng chunk -> max_per_doc -> taint
(fail-closed với class >= 1) -> spotlighting -> output theo schema.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from acme_common.mcp import CallerContext, ToolError
from acme_common.services.taint import raise_taint

from ..normalize import normalize_query
from ..ports import (
    DocumentRetriever,
    Reranker,
    RetrievalUnavailable,
    RetrievedChunk,
)
from . import spotlight
from .acl import AclPolicy

log = logging.getLogger("acme.docs")


class DocumentService:
    def __init__(
        self,
        retriever: DocumentRetriever,
        reranker: Reranker,
        *,
        redis: Any | None,
        recent_ttl_s: int = 86400,
        retention_s: int = 30 * 86400,
        max_per_doc: int = 2,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._redis = redis
        self._recent_ttl_s = recent_ttl_s
        self._retention_s = retention_s
        self._max_per_doc = max_per_doc
        self.taint_write_failures = 0  # => metric docs_taint_write_fail_total

    async def search(
        self,
        ctx: CallerContext,
        query: str,
        top_k: int = 5,
        department_filter: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Trả `(output, audit_info)`."""
        p = ctx.principal
        q = normalize_query(query)
        try:
            res = await self._retriever.search(
                q, p, min(top_k * self._max_per_doc + 4, 60), department_filter
            )
        except RetrievalUnavailable:
            raise ToolError("upstream_unavailable", "document store unavailable") from None
        chunks = await self._reranker.rerank(q, res.chunks)
        # kiểm lại ACL độc lập adapter (loại bỏ, không báo lý do)
        chunks = [
            c
            for c in chunks
            if AclPolicy.can_read(p, c.department, c.classification, c.allowed_roles)
        ]
        chunks = self._limit_per_doc(chunks)[:top_k]

        mode = res.mode
        if chunks:
            ok = await self._write_taint(ctx, chunks)
            if not ok and any(c.classification >= 1 for c in chunks):
                # fail-closed: không trả tài liệu mật khi không ghi được taint
                self.taint_write_failures += 1
                chunks = [c for c in chunks if c.classification == 0]
                mode = "taint_unavailable"
            elif not ok:
                self.taint_write_failures += 1  # class 0: best-effort

        sp = spotlight.new_spotlight()
        results = [
            {
                "rank": i,
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "title": spotlight.sanitize(c.title),
                "heading": spotlight.sanitize(c.heading) if c.heading else None,
                "source": c.source,
                "classification": c.classification,
                "trust": "untrusted",
                "score": round(c.score, 6),
                "vec_rank": c.vec_rank,
                "fts_rank": c.fts_rank,
                "content": spotlight.wrap(c.content, sp),
            }
            for i, c in enumerate(chunks, start=1)
        ]
        out = {
            "query": q,
            "mode": mode,
            "reranked": False,
            "notice": spotlight.notice(sp),
            "spotlight": {
                "delimiter_begin": sp.delimiter_begin,
                "delimiter_end": sp.delimiter_end,
                "datamark": sp.mark,
            },
            "results": results,
            "truncated": False,
        }
        audit = {
            "rows_returned": len(results),
            "tables_read": ["chunks", "documents"],
            "mode": mode,
            "max_class": max((c.classification for c in chunks), default=0),
        }
        return out, audit

    def _limit_per_doc(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        seen: Counter[str] = Counter()
        out: list[RetrievedChunk] = []
        for c in chunks:
            seen[c.doc_id] += 1
            if seen[c.doc_id] <= self._max_per_doc:
                out.append(c)
        return out

    async def _write_taint(self, ctx: CallerContext, chunks: list[RetrievedChunk]) -> bool:
        if self._redis is None:
            return False
        top = max(chunks, key=lambda c: c.classification)
        return await raise_taint(
            self._redis,
            ctx.principal.sub,
            ctx.thread_id,
            top.classification,
            {c.department for c in chunks},
            top.doc_id,
            retention_s=self._retention_s,
            recent_ttl_s=self._recent_ttl_s,
        )
