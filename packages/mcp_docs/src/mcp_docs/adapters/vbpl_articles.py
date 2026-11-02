"""Adapter `DocumentLoader` cho văn bản luật vbpl.vn đã tách theo Điều (`<slug>.json`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..ports.document_loader import DocumentLoader
from ..ports.types import ArticleUnit, Document, DocumentRejected, Section
from ..services.normalize import normalize_text

_SLUG = re.compile(r"^(\d+)-(\d{4})-([a-z0-9]+)$")


def _doc_num(path: Path) -> str:
    """`doc_num` từ manifest.json cùng thư mục theo slug; không có thì suy từ slug."""
    slug = path.stem
    manifest = path.parent / "manifest.json"
    if manifest.is_file():
        try:
            items = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError as e:
            raise DocumentRejected(f"{path.name}: manifest.json is not valid JSON") from e
        for it in items if isinstance(items, list) else []:
            num = it.get("doc_num") if isinstance(it, dict) else None
            if isinstance(num, str) and num.replace("/", "-").lower() == slug:
                return num
    m = _SLUG.match(slug)
    if not m:
        raise DocumentRejected(f"{path.name}: cannot derive doc_num from file name")
    return f"{m.group(1)}/{m.group(2)}/{m.group(3).upper()}"


def _text(v: object, what: str, name: str) -> str:
    if not isinstance(v, str):
        raise DocumentRejected(f"{name}: {what} must be a string")
    return normalize_text(v)


class VbplArticlesLoader(DocumentLoader):
    def load(self, path: Path, *, source_path: str) -> Document:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise DocumentRejected(f"{source_path}: invalid JSON") from e
        if not isinstance(raw, list):
            raise DocumentRejected(f"{source_path}: expected a list of articles")
        doc_num = _doc_num(path)
        sections: list[Section] = []
        seen: set[str] = set()
        for i, item in enumerate(raw):
            if not isinstance(item, dict) or "article" not in item or "paragraphs" not in item:
                raise DocumentRejected(f"{source_path}: item {i} lacks article/paragraphs")
            article = _text(item["article"], "article", source_path)
            if not article:
                raise DocumentRejected(f"{source_path}: item {i} has empty article")
            if article in seen:
                raise DocumentRejected(f"{source_path}: duplicate article {article}")
            seen.add(article)
            paras = item["paragraphs"]
            if not isinstance(paras, list):
                raise DocumentRejected(f"{source_path}: article {article} paragraphs not a list")
            heading = _text(item.get("heading") or "", "heading", source_path)
            chap = item.get("chapter")
            chapter = (_text(chap, "chapter", source_path) or None) if chap is not None else None
            paragraphs = tuple(p for p in (_text(x, "paragraph", source_path) for x in paras) if p)
            unit = ArticleUnit(article, heading, chapter, paragraphs)
            sections.append(Section((f"Điều {article}",), "\n".join(paragraphs), unit))
        return Document(
            source_path,
            f"Văn bản {doc_num}",  # tên đầy đủ do DocumentMeta.title quyết định (job thay vào)
            tuple(sections),
            kind="article",
            doc_num=doc_num,
        )
