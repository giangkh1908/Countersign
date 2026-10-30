"""`Fake<Port>` của docs-mcp cho test nghiệp vụ (contracts §9.1 mục 9). Kế thừa port tường minh."""

from __future__ import annotations

from acme_common.ports import Principal

from .ports import (
    DocumentIndexer,
    DocumentMeta,
    DocumentRetriever,
    Embedder,
    EmbeddingUnavailable,
    IndexedChunk,
    RetrievedChunk,
    SearchResult,
)
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

    async def is_current(self, meta: DocumentMeta) -> bool:
        cur = self.docs.get(meta.id)
        return bool(
            cur
            and cur[1]
            and cur[0].sha256 == meta.sha256
            and cur[0].department == meta.department
            and cur[0].classification == meta.classification
            and cur[0].allowed_roles == meta.allowed_roles
        )

    async def replace(self, meta: DocumentMeta, chunks: list[IndexedChunk]) -> None:
        self.docs[meta.id] = (meta, chunks)


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
