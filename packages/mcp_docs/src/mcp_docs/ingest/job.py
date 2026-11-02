"""Job ingest: metadata ACL -> load -> chunk -> embed -> ghi (1 transaction/tài liệu).

Idempotent: tài liệu đã có chunk với cùng sha256 + ACL thì bỏ qua (trừ `force`). Thiếu hoặc sai
metadata ACL => `DocumentRejected` trước khi ghi bất cứ thứ gì (fail-closed). Embedding lỗi =>
dừng job, không ghi chunk thiếu vector.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..ports import (
    DocumentIndexer,
    DocumentLoader,
    DocumentMeta,
    DocumentRejected,
    Embedder,
    IndexedChunk,
    TextSegmenter,
)
from ..services.chunking import ARTICLE_MAX_TOKENS, CHUNKER_VERSION, embed_text, split
from ..services.index_checks import compute_index_sig, probe_embedder
from ..services.normalize import normalize_text

log = logging.getLogger("acme.docs.ingest")

_DEPT = re.compile(r"^(ALL|[A-Z]{2,12})$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_REQUIRED = ("id", "source_path", "title", "department", "classification", "allowed_roles")


@dataclass
class IngestReport:
    ingested: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    chunks: int = 0


def parse_meta(rec: dict[str, Any]) -> DocumentMeta:
    """Một dòng `documents.jsonl` -> `DocumentMeta`; thiếu/ sai => `DocumentRejected`."""
    missing = [k for k in _REQUIRED if k not in rec or rec[k] is None]
    if missing:
        raise DocumentRejected(f"{rec.get('source_path', '?')}: missing metadata {missing}")
    cls, dept, roles = rec["classification"], rec["department"], rec["allowed_roles"]
    if isinstance(cls, bool) or not isinstance(cls, int) or not 0 <= cls <= 3:
        raise DocumentRejected(f"{rec['source_path']}: classification must be 0..3")
    if not isinstance(dept, str) or not _DEPT.match(dept):
        raise DocumentRejected(f"{rec['source_path']}: invalid department")
    if not isinstance(roles, list) or not all(isinstance(r, str) and r for r in roles):
        raise DocumentRejected(f"{rec['source_path']}: allowed_roles must be a list of strings")
    if not isinstance(rec["id"], str) or not _UUID.match(rec["id"]):
        raise DocumentRejected(f"{rec['source_path']}: id must be a lowercase uuid")
    if not str(rec["title"]).strip():
        raise DocumentRejected(f"{rec['source_path']}: empty title")
    doc_num = rec.get("doc_num")
    if doc_num is not None and (not isinstance(doc_num, str) or not doc_num.strip()):
        raise DocumentRejected(f"{rec['source_path']}: doc_num must be a non-empty string")
    if rec.get("kind") == "van_ban_phap_luat" and doc_num is None:
        raise DocumentRejected(f"{rec['source_path']}: doc_num is required for van_ban_phap_luat")
    return DocumentMeta(
        id=rec["id"],
        source_path=rec["source_path"],
        title=normalize_text(rec["title"]),
        sha256=str(rec.get("sha256", "")),
        department=dept,
        classification=cls,
        allowed_roles=tuple(roles),
        owner_sub=rec.get("owner_sub"),
        version=int(rec.get("version", 1)),
        doc_num=doc_num,
    )


def load_metadata(corpus_dir: Path) -> list[DocumentMeta]:
    path = corpus_dir / "documents.jsonl"
    if not path.is_file():
        raise DocumentRejected(f"missing {path.name} in {corpus_dir}")
    metas = [
        parse_meta(json.loads(ln))
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    if len({m.id for m in metas}) != len(metas):
        raise DocumentRejected("duplicate document id in metadata")
    return metas


async def run_ingest(
    corpus_dir: Path,
    *,
    loader_for: Callable[[Path], DocumentLoader],
    embedder: Embedder,
    indexer: DocumentIndexer,
    force: bool = False,
    article_max_tokens: int = ARTICLE_MAX_TOKENS,
    segmenter: TextSegmenter | None = None,
    verify: bool = True,
) -> IngestReport:
    """`verify`: kiểm cột embedding và thăm dò embedder trước khi ghi (sai chiều => `IndexConfigError`).

    `index_sig`/`index_meta` dùng `embedder.model_id` (id model thật). Với `verify=False` embedder
    chưa được gọi nên id có thể mới là alias cấu hình.
    """
    metas = load_metadata(corpus_dir)
    dim = embedder.dim
    if verify:
        await indexer.verify_schema(dim)
        await probe_embedder(embedder, dim)
    embed_model = embedder.model_id  # sau probe: id model thật, không phải alias
    seg_name = segmenter.name if segmenter else "-"
    index_sig = compute_index_sig(
        chunker_version=CHUNKER_VERSION,
        embed_model=embed_model,
        embed_dim=dim,
        article_max_tokens=article_max_tokens,
        segmenter=seg_name,
    )
    # kiểm tra mọi file trước khi ghi: fail sớm, không ghi dở
    files: dict[str, Path] = {}
    root = corpus_dir.resolve()  # noqa: ASYNC240 - đọc đĩa một lần lúc khởi động job
    for m in metas:
        f = (corpus_dir / m.source_path).resolve()
        if not f.is_relative_to(root) or not f.is_file():
            raise DocumentRejected(f"{m.source_path}: file not found under corpus dir")
        files[m.id] = f

    report = IngestReport()
    for m in metas:
        f = files[m.id]
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        meta = m if actual == m.sha256 else _with_sha(m, actual)
        if not force and await indexer.is_current(meta, index_sig):
            report.skipped.append(meta.source_path)
            continue
        doc = loader_for(f).load(f, source_path=meta.source_path)
        if doc.kind == "article":  # tên văn bản và số hiệu do metadata quyết định
            doc = replace(doc, title=meta.title, doc_num=meta.doc_num or doc.doc_num)
        chunks = split(doc, article_max_tokens=article_max_tokens)
        if not chunks:
            raise DocumentRejected(f"{meta.source_path}: no content to index")
        title = doc.title if doc.kind == "article" else None
        vectors = await embedder.embed([embed_text(c, title) for c in chunks])
        await indexer.replace(
            meta,
            [
                IndexedChunk(c, v, segmenter.segment(c.content) if segmenter else None)
                for c, v in zip(chunks, vectors, strict=True)
            ],
            index_sig,
        )
        report.ingested.append(meta.source_path)
        report.chunks += len(chunks)
        log.info("ingested %s (%d chunks)", meta.source_path, len(chunks))
    if report.ingested:
        await indexer.record_index_meta(
            {
                "embed_model": embed_model,
                "embed_dim": str(dim),
                "chunker_version": CHUNKER_VERSION,
                "segmenter": seg_name,
            }
        )
    return report


def _with_sha(m: DocumentMeta, sha: str) -> DocumentMeta:
    return DocumentMeta(
        id=m.id,
        source_path=m.source_path,
        title=m.title,
        sha256=sha,
        department=m.department,
        classification=m.classification,
        allowed_roles=m.allowed_roles,
        owner_sub=m.owner_sub,
        version=m.version,
        doc_num=m.doc_num,
    )
