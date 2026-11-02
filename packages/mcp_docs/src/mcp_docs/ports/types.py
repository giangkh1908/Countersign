"""Kiểu trung lập ở biên các port của docs-mcp. Không phụ thuộc vendor."""

from __future__ import annotations

from dataclasses import dataclass


class RetrievalUnavailable(Exception):
    """Kho tài liệu không truy vấn được. `kind` thuộc tập hữu hạn, message không chứa dữ liệu người dùng."""

    def __init__(self, kind: str, *, retryable: bool = True) -> None:
        super().__init__(f"retrieval_unavailable: {kind}")
        self.kind = kind
        self.retryable = retryable


class EmbeddingUnavailable(Exception):
    """Embedder không trả vector (gateway lỗi, sai chiều...). Query: suy giảm sang fts_only; ingest: dừng."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"embedding_unavailable: {kind}")
        self.kind = kind


class RerankUnavailable(Exception):
    """Reranker không trả điểm (gateway lỗi/timeout, sai dạng). Truy xuất bỏ qua rerank, vẫn trả kết quả."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"rerank_unavailable: {kind}")
        self.kind = kind


class DocumentRejected(Exception):
    """Tài liệu/metadata không hợp lệ (ingest fail-closed)."""


class IndexConfigError(Exception):
    """Cấu hình lệch với chỉ mục (sai số chiều, lẫn model embedding...). Dừng dịch vụ, không suy giảm."""


@dataclass(frozen=True, slots=True)
class Ref:
    """Tham chiếu pháp lý trong câu hỏi: Điều (và khoản) của một văn bản, đã hoặc chưa xác định."""

    article: str | None = None
    clause: str | None = None
    doc_num: str | None = None
    doc_hint: str | None = None  # tên văn bản nêu trong câu, chưa giải thành `doc_num`


@dataclass(frozen=True, slots=True)
class ArticleUnit:
    """Một Điều của văn bản luật (đính vào `Section.unit` khi `Document.kind == "article"`)."""

    article: str  # "38", "38a"
    heading: str
    chapter: str | None
    paragraphs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Section:
    """Một mục của tài liệu. `path` = đường dẫn heading từ gốc; `body` là văn bản của riêng mục."""

    path: tuple[str, ...]
    body: str
    unit: ArticleUnit | None = None


@dataclass(frozen=True, slots=True)
class Document:
    source_path: str
    title: str
    sections: tuple[Section, ...]
    kind: str = "markdown"  # markdown | article
    doc_num: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Metadata ACL bắt buộc của tài liệu (thiếu hoặc sai => DocumentRejected)."""

    id: str
    source_path: str
    title: str
    sha256: str
    department: str
    classification: int
    allowed_roles: tuple[str, ...] = ()
    owner_sub: str | None = None
    version: int = 1
    doc_num: str | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    ord: int
    heading: str | None
    content: str
    n_tokens: int
    article: str | None = None
    clause: str | None = None
    chapter: str | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: int
    doc_id: str
    title: str
    heading: str | None
    source: str  # source_path#ord, dùng để trích dẫn
    ord: int
    department: str
    classification: int
    allowed_roles: tuple[str, ...]
    content: str
    score: float = 0.0
    vec_rank: int | None = None
    fts_rank: int | None = None
    doc_num: str | None = None
    article: str | None = None
    clause: str | None = None
    chapter: str | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunks: list[RetrievedChunk]
    mode: str = "hybrid"  # hybrid | vector_only | fts_only
