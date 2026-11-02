"""Tra trực tiếp: ghim chunk của "Điều N <văn bản>" lên đầu, vẫn qua ACL, tắt khi `off`."""

from __future__ import annotations

from dataclasses import replace

import fakeredis.aioredis
from acme_common.mcp import CallerContext
from acme_common.ports import Principal
from mcp_docs.adapters.none import NoReranker
from mcp_docs.services.document_service import DocumentService
from mcp_docs.testing import FakeArticleReader, FakeRetriever, make_chunk


def law(i: int, article: str, clause: str | None, *, dept="ALL", cls=0, doc="45/2019/QH14"):
    return replace(
        make_chunk(i, dept, cls),
        title="Bộ luật Lao động",
        doc_num=doc,
        article=article,
        clause=clause,
    )


STORE = [law(10, "38", "1"), law(11, "38", "2"), law(12, "38", "3"), law(13, "5", None)]
NOISE = [make_chunk(1, "ALL", 0), make_chunk(2, "ALL", 0)]


def ctx(clearance: int = 0, dept: tuple[str, ...] = ()):
    p = Principal(
        sub="u1",
        audience=("docs-mcp",),
        azp="agent-service",
        scopes=frozenset({"docs:read"}),
        expires_at=1e12,
        dept=dept,
        clearance=clearance,
        roles=("employee",),
    )
    return CallerContext(principal=p, request_id="r", thread_id="t1")


def service(reader, mode="pin", store=NOISE):
    return DocumentService(
        FakeRetriever(list(store)),
        NoReranker(),
        redis=fakeredis.aioredis.FakeRedis(),
        article_reader=reader,
        direct_lookup=mode,
    )


async def test_pin_puts_article_chunks_first_with_clause_priority() -> None:
    svc = service(FakeArticleReader(STORE))
    out, audit = await svc.search(ctx(), "khoản 2 Điều 38 Bộ luật Lao động", top_k=5)
    ids = [r["chunk_id"] for r in out["results"]]
    assert ids[:3] == [11, 10, 12]  # khoản 2 đứng trước, cùng Điều
    assert ids[3:] == [1, 2]
    assert out["direct"] == 3 and audit["direct"] == 3 and audit["refs_unresolved"] == 0


async def test_off_does_not_touch_reader() -> None:
    reader = FakeArticleReader(STORE)
    out, _ = await service(reader, mode="off").search(ctx(), "Điều 38 Bộ luật Lao động")
    assert reader.reads == [] and out["direct"] == 0


async def test_no_article_in_query_skips_lookup() -> None:
    reader = FakeArticleReader(STORE)
    out, _ = await service(reader).search(ctx(), "nghỉ phép năm bao nhiêu ngày")
    assert reader.reads == [] and out["direct"] == 0


async def test_unknown_or_ambiguous_document_is_not_pinned() -> None:
    reader = FakeArticleReader([*STORE, law(20, "38", None, doc="10/2012/QH13")])
    out, audit = await service(reader).search(ctx(), "Điều 38 Bộ luật Lao động")
    assert out["direct"] == 0 and audit["refs_unresolved"] == 1  # hai văn bản cùng tên
    out, audit = await service(FakeArticleReader(STORE)).search(ctx(), "Điều 38 Luật Đất đai")
    assert out["direct"] == 0 and audit["refs_unresolved"] == 1


async def test_pinned_chunks_still_pass_acl() -> None:
    secret = [law(30, "7", None, dept="HR", cls=3)]

    # reader rò (không lọc) vẫn bị service lọc lại
    class LeakyReader(FakeArticleReader):
        async def read(self, refs, principal):  # type: ignore[no-untyped-def]
            return list(self.chunks)

    svc = service(LeakyReader(secret))
    out, _ = await svc.search(ctx(clearance=0), "Điều 7 45/2019/QH14")
    assert out["direct"] == 0 and 30 not in [r["chunk_id"] for r in out["results"]]


async def test_fake_reader_enforces_acl() -> None:
    secret = [law(30, "7", None, dept="HR", cls=3)]
    out, _ = await service(FakeArticleReader(secret)).search(ctx(), "Điều 7 45/2019/QH14")
    assert out["direct"] == 0
    out, _ = await service(FakeArticleReader(secret)).search(
        ctx(clearance=3, dept=("HR",)), "Điều 7 45/2019/QH14"
    )
    assert out["direct"] == 1


async def test_reader_failure_degrades_to_retrieval() -> None:
    out, _ = await service(FakeArticleReader(STORE, fail=True)).search(
        ctx(), "Điều 38 Bộ luật Lao động"
    )
    assert out["direct"] == 0 and len(out["results"]) == 2
