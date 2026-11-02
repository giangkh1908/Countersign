"""Kiểu `Passage`/`Citation` và `CitationResolver` (rag-citations §5.1, §5.2).

Mô hình trích bằng mã `[#<chunk_id>]`; chỉ chunk có trong `retrieved` (do docs-mcp trả trong lượt này)
mới được giữ. Nội dung `Citation` luôn dựng từ `Passage`, không từ văn bản do mô hình viết.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

MAX_ITEMS = 8  # trần số nguồn trong một khung `citations` (rag-citations §5.4)
SNIPPET_CHARS = 300
PASSAGE_CHARS = 4000

# `[#12]`, `[#12][#15]`, `[#12, #15]`, `[#12; 15]`
_REF = re.compile(r"\s*\[\s*#\d+(?:\s*[,;]\s*#?\d+)*\s*\]")
_ID = re.compile(r"\d+")


class Passage(BaseModel):
    """Một đoạn do `search_documents` trả về trong lượt (dữ liệu của docs-mcp, không phải của mô hình)."""

    chunk_id: int
    doc_id: str
    doc_num: str | None = None
    title: str = ""
    heading: str | None = None
    article: str | None = None
    clause: str | None = None
    chapter: str | None = None
    chunk_ord: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    text: str = ""
    score: float | None = None


class Citation(BaseModel):
    n: int
    doc_id: str
    doc_num: str | None = None
    title: str = ""
    article: str | None = None
    clause: str | None = None
    chapter: str | None = None
    heading: str | None = None
    chunk_ord: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    snippet: str = ""
    passage: str = ""
    passage_truncated: bool = False
    evidence_start: int | None = None
    evidence_end: int | None = None
    verdict: Literal["supported", "partial", "unsupported", "unverified"] = "unverified"
    sentence_ids: list[int] = []
    score: float | None = None

    @classmethod
    def from_passage(cls, n: int, p: Passage) -> Citation:
        return cls(
            n=n,
            doc_id=p.doc_id,
            doc_num=p.doc_num,
            title=p.title,
            article=p.article,
            clause=p.clause,
            chapter=p.chapter,
            heading=p.heading,
            chunk_ord=p.chunk_ord,
            char_start=p.char_start,
            char_end=p.char_end,
            snippet=p.text[:SNIPPET_CHARS],
            passage=p.text[:PASSAGE_CHARS],
            passage_truncated=len(p.text) > PASSAGE_CHARS,
            score=p.score,
        )


@dataclass
class ResolveResult:
    text: str
    order: list[int] = field(default_factory=list)  # chunk_id, theo thứ tự n = 1, 2, ...
    invalid_refs: int = 0


def passage_from_result(r: dict[str, Any]) -> Passage | None:
    """Dựng `Passage` từ một phần tử `results[]` của `search_documents`."""
    if not isinstance(r, dict) or "doc_id" not in r or not isinstance(r.get("chunk_id"), int):
        return None
    source = str(r.get("source", ""))
    ord_ = source.rsplit("#", 1)[-1] if "#" in source else ""
    text = r.get("text")
    if not isinstance(text, str):
        text = str(r.get("content", ""))
    return Passage(
        chunk_id=r["chunk_id"],
        doc_id=str(r["doc_id"]),
        doc_num=r.get("doc_num"),
        title=str(r.get("title", "")),
        heading=r.get("heading"),
        article=r.get("article"),
        clause=r.get("clause"),
        chapter=r.get("chapter"),
        chunk_ord=int(ord_) if ord_.isdigit() else None,
        char_start=r.get("char_start"),
        char_end=r.get("char_end"),
        text=text,
        score=r.get("score"),
    )


class CitationResolver:
    """`[#id]` -> `[n]` theo thứ tự xuất hiện; mã ngoài `retrieved` bị xoá khỏi văn bản."""

    def __init__(self, max_items: int = MAX_ITEMS) -> None:
        self._max = max_items

    def resolve(self, draft: str, retrieved: dict[str, Passage]) -> ResolveResult:
        order: list[int] = []
        invalid = 0

        def sub(m: re.Match[str]) -> str:
            nonlocal invalid
            ns: list[int] = []
            for raw in _ID.findall(m.group(0)):
                cid = int(raw)
                if str(cid) not in retrieved:
                    invalid += 1
                    continue
                if cid not in order:
                    if len(order) >= self._max:
                        invalid += 1
                        continue
                    order.append(cid)
                ns.append(order.index(cid) + 1)
            if not ns:
                return ""  # xoá cả khoảng trắng đứng trước mã
            lead = m.group(0)[: len(m.group(0)) - len(m.group(0).lstrip())]
            return lead + "".join(f"[{n}]" for n in dict.fromkeys(ns))

        return ResolveResult(_REF.sub(sub, draft), order, invalid)
