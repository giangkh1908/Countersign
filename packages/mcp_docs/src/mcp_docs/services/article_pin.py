"""`ArticlePinner`: tra trực tiếp "Điều N <văn bản>" nêu trong câu hỏi, dùng chung cho service và eval.

Chỉ phụ thuộc port `ArticleReader` (ACL do adapter thực thi). Không bao giờ nới quyền: lỗi kho
thì trả rỗng để truy xuất chính vẫn chạy.
"""

from __future__ import annotations

import logging
from typing import Any

from ..ports import ArticleReader, Ref, RetrievalUnavailable, RetrievedChunk
from ..refs import clause_matches, parse_refs

log = logging.getLogger("acme.docs")


class ArticlePinner:
    def __init__(self, reader: ArticleReader) -> None:
        self._reader = reader

    async def pin(self, query: str, principal: Any) -> tuple[list[RetrievedChunk], int]:
        """Chunk của các Điều nêu trong câu hỏi và số tham chiếu chưa giải được."""
        refs = parse_refs(query)
        if not refs:
            return [], 0
        try:
            resolved: list[Ref] = []
            hints: dict[str, str | None] = {}
            for r in refs:
                if r.doc_num is None and r.doc_hint:
                    if r.doc_hint not in hints:
                        found = await self._reader.find_documents(r.doc_hint, principal)
                        hints[r.doc_hint] = found[0][0] if len(found) == 1 else None
                    r = Ref(r.article, r.clause, hints[r.doc_hint], r.doc_hint)
                resolved.append(r)
            ok = [r for r in resolved if r.doc_num and r.article]
            found_chunks = await self._reader.read(ok, principal) if ok else []
        except RetrievalUnavailable:
            log.warning("direct lookup unavailable; continuing with retrieval only")
            return [], len(refs)
        pinned: list[RetrievedChunk] = []
        seen: set[int] = set()
        for r in ok:
            mine = [c for c in found_chunks if c.doc_num == r.doc_num and c.article == r.article]
            if r.clause:  # chunk chứa khoản được hỏi đứng trước
                hit = [c for c in mine if clause_matches(c.clause, r.clause)]
                mine = hit + [c for c in mine if c not in hit]
            for c in mine:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    pinned.append(c)
        return pinned, len(refs) - len(ok)
