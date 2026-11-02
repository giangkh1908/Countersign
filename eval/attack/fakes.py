"""Fake của port `DocumentRetriever` cho harness: chấm điểm trùng từ khoá, có kiểm ACL như adapter thật."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from acme_common.ports import Principal
from mcp_docs.adapters.markdown import MarkdownLoader
from mcp_docs.ingest.job import load_metadata
from mcp_docs.ports import DocumentRetriever, RetrievedChunk, SearchResult
from mcp_docs.services.acl import AclPolicy
from mcp_docs.services.chunking import split
from mcp_docs.services.normalize import normalize_query

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(s: str) -> set[str]:
    return set(_TOKEN.findall(s.lower()))


class KeywordRetriever(DocumentRetriever):
    """`enforce_acl=False` mô phỏng adapter rò (service phải lọc lại)."""

    def __init__(self, chunks: list[RetrievedChunk], *, enforce_acl: bool = True) -> None:
        self.chunks = chunks
        self.enforce_acl = enforce_acl
        self._tok = [_tokens(f"{c.title} {c.heading or ''} {c.content}") for c in chunks]
        df = Counter(t for toks in self._tok for t in toks)
        self._idf = {t: math.log(1 + len(chunks) / n) for t, n in df.items()}  # từ hiếm nặng hơn

    async def search(
        self, query: str, principal: Principal, k: int, department_filter: str | None = None
    ) -> SearchResult:
        q = _tokens(normalize_query(query))
        scored: list[tuple[float, int, RetrievedChunk]] = []
        for i, (c, toks) in enumerate(zip(self.chunks, self._tok, strict=True)):
            if self.enforce_acl and not AclPolicy.can_read(
                principal, c.department, c.classification, c.allowed_roles
            ):
                continue
            if department_filter and c.department != department_filter:
                continue
            score = sum(self._idf[t] for t in q & toks)
            if score:
                scored.append((-score, i, c))
        scored.sort(key=lambda t: (t[0], t[1]))
        return SearchResult([c for _, _, c in scored[:k]], "fts_only")


def load_chunks(corpus_dir: Path) -> list[RetrievedChunk]:
    """Nạp corpus bằng đúng loader + chunker của ingest (không DB, không embedding)."""
    out: list[RetrievedChunk] = []
    cid = 0
    for m in load_metadata(corpus_dir):
        doc = MarkdownLoader().load(corpus_dir / m.source_path, source_path=m.source_path)
        for c in split(doc):
            cid += 1
            out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    doc_id=m.id,
                    title=m.title,
                    heading=c.heading,
                    source=f"{m.source_path}#{c.ord}",
                    ord=c.ord,
                    department=m.department,
                    classification=m.classification,
                    allowed_roles=m.allowed_roles,
                    content=c.content,
                )
            )
    return out
