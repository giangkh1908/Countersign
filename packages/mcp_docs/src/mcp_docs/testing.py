"""`Fake<Port>` của docs-mcp cho test nghiệp vụ (contracts §9.1 mục 9). Kế thừa port tường minh."""

from __future__ import annotations

from acme_common.ports import Principal

from .ports import (
    ArticleReader,
    DocumentIndexer,
    DocumentMeta,
    DocumentRetriever,
    Embedder,
    EmbeddingUnavailable,
    IndexedChunk,
    Ref,
    RetrievalUnavailable,
    RetrievedChunk,
    SearchResult,
)
from .refs import fold
from .services.acl import AclPolicy


class FakeRetriever(DocumentRetriever):
    """Kho trong bộ nhớ. `enforce_acl=False` mô phỏng adapter lỗi/rò (để chứng minh service lọc lại)."""

    def __init__(
        self, chunks: list[RetrievedChunk], *, enforce_acl: bool = True, mode: str = "hybrid"
    ) -> None:
        self.chunks = chunks
        self.enforce_acl = enforce_acl
        self.mode = mode
        self.calls: list[tuple[str, int, str | None]] = []

    async def search(
        self,
        query: str,
        principal: Principal,
        k: int,
        department_filter: str | None = None,
    ) -> SearchResult:
        self.calls.append((query, k, department_filter))
        out = [
            c
            for c in self.chunks
            if (not self.enforce_acl)
            or AclPolicy.can_read(principal, c.department, c.classification, c.allowed_roles)
        ]
        if department_filter:
            out = [c for c in out if c.department == department_filter]
        return SearchResult(out[:k], self.mode)


class FakeIndexer(DocumentIndexer):
    def __init__(self) -> None:
        self.docs: dict[str, tuple[DocumentMeta, list[IndexedChunk]]] = {}
        self.sigs: dict[str, str] = {}
        self.index_meta: dict[str, str] = {}
        self.verified_dim: int | None = None

    async def verify_schema(self, expected_dim: int) -> None:
        self.verified_dim = expected_dim

    async def record_index_meta(self, values: dict[str, str]) -> None:
        self.index_meta.update(values)

    async def is_current(self, meta: DocumentMeta, index_sig: str = "") -> bool:
        cur = self.docs.get(meta.id)
        return bool(
            cur
            and cur[1]
            and self.sigs.get(meta.id, "") == index_sig
            and cur[0].sha256 == meta.sha256
            and cur[0].department == meta.department
            and cur[0].classification == meta.classification
            and cur[0].allowed_roles == meta.allowed_roles
        )

    async def replace(
        self, meta: DocumentMeta, chunks: list[IndexedChunk], index_sig: str = ""
    ) -> None:
        self.docs[meta.id] = (meta, chunks)
        self.sigs[meta.id] = index_sig


class FakeArticleReader(ArticleReader):
    """Tra trực tiếp trong bộ nhớ, vẫn lọc theo quyền (như adapter thật)."""

    def __init__(self, chunks: list[RetrievedChunk], *, fail: bool = False) -> None:
        self.chunks = chunks
        self.fail = fail
        self.reads: list[list[Ref]] = []

    async def read(self, refs: list[Ref], principal: Principal) -> list[RetrievedChunk]:
        if self.fail:
            raise RetrievalUnavailable("test")
        self.reads.append(refs)
        return [
            c
            for r in refs
            for c in self.chunks
            if r.doc_num == c.doc_num
            and r.article == c.article
            and AclPolicy.can_read(principal, c.department, c.classification, c.allowed_roles)
        ]

    async def find_documents(self, hint: str, principal: Principal) -> list[tuple[str, str]]:
        key = hint.lower()
        seen: dict[str, str] = {}
        for c in self.chunks:
            if (
                c.doc_num
                and fold(key) in fold(c.title)
                and AclPolicy.can_read(principal, c.department, c.classification, c.allowed_roles)
            ):
                seen[c.doc_num] = c.title
        return list(seen.items())


class FailingEmbedder(Embedder):
    @property
    def dim(self) -> int:
        return 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingUnavailable("test")


def make_chunk(
    i: int, dept: str, cls: int, roles: tuple[str, ...] = (), content: str = ""
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=i,
        doc_id=f"00000000-0000-0000-0000-{i:012d}",
        title=f"Tài liệu {i}",
        heading="Mục",
        source=f"corpus/{dept}/{i}.md#0",
        ord=0,
        department=dept,
        classification=cls,
        allowed_roles=roles,
        content=content or f"Nội dung số {i} về lương thưởng",
        score=1 / i,
    )


SAMPLE_STORE = [
    make_chunk(1, "ALL", 0),
    make_chunk(2, "ALL", 1),
    make_chunk(3, "SALES", 2),
    make_chunk(4, "HR", 2),
    make_chunk(5, "HR", 3, ("dept_manager",)),
]
