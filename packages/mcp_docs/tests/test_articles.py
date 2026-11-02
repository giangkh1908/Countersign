"""Loader vbpl_articles + chunking theo Điều (rag-citations §1.2-1.6)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp_docs.adapters.vbpl_articles import VbplArticlesLoader
from mcp_docs.factory import build_loader
from mcp_docs.ports import Chunk, Document, DocumentRejected
from mcp_docs.services.chunking import (
    HARD_MAX,
    SOFT_MAX,
    article_text,
    count_tokens,
    embed_text,
    split,
)
from mcp_docs.settings import Settings


def words(n: int, prefix: str = "từ") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def write(tmp_path: Path, arts: object, name: str = "45-2019-qh14.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")
    return p


def art(article: str, paras: list[str], heading: str = "Tiêu đề", chapter: str | None = None):
    return {"article": article, "heading": heading, "chapter": chapter, "paragraphs": paras}


def load(tmp_path: Path, arts: object, name: str = "45-2019-qh14.json") -> Document:
    return VbplArticlesLoader().load(write(tmp_path, arts, name), source_path=name)


def check_invariants(doc: Document, chunks: list[Chunk]) -> None:
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    by_article: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_article.setdefault(c.article or "", []).append(c)
    for sec in doc.sections:
        assert sec.unit is not None
        at = article_text(sec.unit)
        cs = by_article[sec.unit.article]
        prev_end = 0
        for c in cs:
            assert c.char_start is not None and c.char_end is not None
            assert at[c.char_start : c.char_end] == c.content
            assert c.char_start >= prev_end  # không chồng nhau
            assert at[prev_end : c.char_start].strip() == ""  # khoảng hở chỉ là khoảng trắng biên
            prev_end = c.char_end
        assert prev_end == len(at) and cs[0].char_start == 0


# --- loader ---


def test_loader_basic_and_slug_doc_num(tmp_path: Path) -> None:
    d = load(tmp_path, [art("1", ["a"], chapter="Chương I"), art("38a", ["b", "c"])])
    assert d.kind == "article" and d.doc_num == "45/2019/QH14"
    assert [s.unit.article for s in d.sections if s.unit] == ["1", "38a"]
    assert d.sections[0].unit.chapter == "Chương I"  # type: ignore[union-attr]
    assert d.sections[1].unit.paragraphs == ("b", "c")  # type: ignore[union-attr]


def test_loader_doc_num_from_manifest(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps([{"doc_num": "45/2019/QH14"}]), encoding="utf-8"
    )
    assert load(tmp_path, [art("1", ["a"])]).doc_num == "45/2019/QH14"


def test_loader_normalizes_text(tmp_path: Path) -> None:
    d = load(tmp_path, [art("1", ["Lao​ động  tốt"], heading="Điều​ khoản")])
    assert d.sections[0].unit.paragraphs == ("Lao động tốt",)  # type: ignore[union-attr]
    assert d.sections[0].unit.heading == "Điều khoản"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "arts",
    [
        {"not": "a list"},
        [{"article": "1"}],
        [{"paragraphs": ["x"]}],
        [art("1", ["a"]), art("1", ["b"])],
        [art("1", "không phải list")],  # type: ignore[arg-type]
    ],
)
def test_loader_rejects_bad_schema(tmp_path: Path, arts: object) -> None:
    with pytest.raises(DocumentRejected):
        load(tmp_path, arts)


def test_loader_rejects_unknown_slug(tmp_path: Path) -> None:
    with pytest.raises(DocumentRejected, match="doc_num"):
        load(tmp_path, [art("1", ["a"])], name="abc.json")


def test_factory_maps_json_to_vbpl_loader() -> None:
    assert isinstance(build_loader(".json", Settings()), VbplArticlesLoader)


# --- chia chunk ---


def test_short_article_is_one_chunk_with_offsets(tmp_path: Path) -> None:
    d = load(tmp_path, [art("1", ["Nội dung ngắn."], chapter="Chương I")])
    [c] = split(d)
    assert c.content == "Điều 1. Tiêu đề\nNội dung ngắn."
    assert (c.article, c.clause, c.chapter) == ("1", None, "Chương I")
    assert (c.char_start, c.char_end) == (0, len(c.content))
    assert c.heading == "Điều 1. Tiêu đề"
    check_invariants(d, [c])


def test_empty_article_keeps_heading_only_chunk(tmp_path: Path) -> None:
    d = load(tmp_path, [art("5", [])])
    [c] = split(d)
    assert c.content == "Điều 5. Tiêu đề"
    check_invariants(d, [c])


def test_small_clauses_merge_into_range(tmp_path: Path) -> None:
    paras = [words(5, "dẫn")] + [f"{i}. {words(60, f'k{i}_')}" for i in range(1, 4)]
    d = load(tmp_path, [art("9", paras)])
    chunks = split(d, article_max_tokens=100)
    assert [c.clause for c in chunks] == ["1-3"]
    assert chunks[0].content.startswith("Điều 9.")  # phần dẫn + tiêu đề cùng chunk
    check_invariants(d, chunks)


def test_big_clauses_stay_separate(tmp_path: Path) -> None:
    paras = ["Phần dẫn."] + [f"{i}. {words(400, f'k{i}_')}" for i in range(1, 4)]
    d = load(tmp_path, [art("9", paras)])
    chunks = split(d)
    assert [c.clause for c in chunks] == ["1", "2", "3"]
    check_invariants(d, chunks)


def test_clause_numbers_must_be_sequential(tmp_path: Path) -> None:
    # "5. " không phải khoản kế tiếp nên thuộc khoản 1; không có khoản "2" => không tách
    paras = ["Mở đầu.", f"1. {words(400)}", f"5. {words(400, 'y')}"]
    d = load(tmp_path, [art("9", paras)])
    chunks = split(d)
    assert {c.clause for c in chunks} <= {None, "1"}
    check_invariants(d, chunks)


def test_long_clause_cut_by_points(tmp_path: Path) -> None:
    paras = ["1. Các trường hợp sau:"] + [f"{ch}) {words(300, ch)}" for ch in "abcd"]
    d = load(tmp_path, [art("7", paras)])
    chunks = split(d)
    assert len(chunks) >= 3
    assert {c.clause for c in chunks} == {"1"}
    assert all(c.n_tokens <= SOFT_MAX for c in chunks)
    # chunk con (trừ chunk đầu) bắt đầu ở ranh giới điểm
    assert all(c.content.startswith(("a)", "b)", "c)", "d)")) or c.ord == 0 for c in chunks)
    check_invariants(d, chunks)


def test_long_paragraph_cut_by_sentence_then_words(tmp_path: Path) -> None:
    sent = " ".join(["Câu"] + [f"w{i}" for i in range(80)]) + "."
    d = load(tmp_path, [art("3", ["1. " + " ".join([sent] * 12)]), art("4", [words(3000)])])
    chunks = split(d)
    assert all(c.n_tokens <= HARD_MAX for c in chunks)
    assert len([c for c in chunks if c.article == "4"]) >= 6
    check_invariants(d, chunks)


def test_deterministic_two_runs(tmp_path: Path) -> None:
    paras = ["Dẫn."] + [f"{i}. {words(250, f'k{i}_')}" for i in range(1, 6)]
    d = load(tmp_path, [art("1", paras), art("2", [words(2000)])])
    assert split(d) == split(load(tmp_path, [art("1", paras), art("2", [words(2000)])]))


def test_ord_global_across_articles(tmp_path: Path) -> None:
    d = load(tmp_path, [art("1", ["a"]), art("2", ["b"]), art("3", ["c"])])
    chunks = split(d)
    assert [(c.ord, c.article) for c in chunks] == [(0, "1"), (1, "2"), (2, "3")]


def test_split_requires_unit() -> None:
    from mcp_docs.ports import Section

    bad = Document("x.json", "X", (Section(("Điều 1",), "b"),), kind="article")
    with pytest.raises(DocumentRejected):
        split(bad)


def test_embed_text_adds_doc_title_without_changing_content(tmp_path: Path) -> None:
    d = load(tmp_path, [art("1", ["Nội dung."])])
    [c] = split(d)
    t = embed_text(c, "Bộ luật Lao động")
    assert t == "Bộ luật Lao động — Điều 1. Tiêu đề\nNội dung."
    assert embed_text(c) == c.content  # heading không bị lặp


def test_markdown_split_unchanged_default_fields() -> None:
    from mcp_docs.ports import Section

    [c] = split(Document("a.md", "A", (Section(("H",), words(130)),)))
    assert (c.article, c.clause, c.char_start) == (None, None, None)
    assert count_tokens(c.content) == c.n_tokens


# --- dữ liệu thật ---

RAW = Path(os.environ.get("VBPL_RAW_DIR", Path(__file__).parents[3] / "data" / "raw" / "vbpl"))


@pytest.mark.skipif(not (RAW / "manifest.json").is_file(), reason="chưa có data/raw/vbpl")
def test_real_corpus_counts_and_invariants() -> None:
    files = sorted(p for p in RAW.glob("*.json") if p.name != "manifest.json")
    assert len(files) == 19
    loader = VbplArticlesLoader()
    total_articles = 0
    for f in files:
        d = loader.load(f, source_path=f.name)
        chunks = split(d)
        total_articles += len(d.sections)
        assert {c.article for c in chunks} == {s.unit.article for s in d.sections if s.unit}
        check_invariants(d, chunks)
        assert chunks == split(loader.load(f, source_path=f.name))
    assert total_articles == 1557


# --- ingest văn bản luật ---


def test_parse_meta_requires_doc_num_for_law() -> None:
    from mcp_docs.ingest.job import parse_meta

    rec = {
        "id": "11111111-1111-4111-8111-111111111111",
        "source_path": "45-2019-qh14.json",
        "title": "Bộ luật Lao động",
        "department": "HR",
        "classification": 1,
        "allowed_roles": [],
        "kind": "van_ban_phap_luat",
    }
    with pytest.raises(DocumentRejected, match="doc_num"):
        parse_meta(rec)
    assert parse_meta({**rec, "doc_num": "45/2019/QH14"}).doc_num == "45/2019/QH14"


async def test_ingest_law_file_is_idempotent(tmp_path: Path) -> None:
    import hashlib

    from mcp_docs.adapters.fake_hash import FakeHashEmbedder
    from mcp_docs.ingest.job import run_ingest
    from mcp_docs.testing import FakeIndexer

    f = write(tmp_path, [art("1", ["Nội dung."]), art("2", [words(2000)])])
    rec = {
        "id": "11111111-1111-4111-8111-111111111111",
        "source_path": f.name,
        "title": "Bộ luật Lao động",
        "doc_num": "45/2019/QH14",
        "kind": "van_ban_phap_luat",
        "department": "HR",
        "classification": 1,
        "allowed_roles": [],
        "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
    }
    (tmp_path / "documents.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    idx = FakeIndexer()
    emb = FakeHashEmbedder()

    async def go():
        return await run_ingest(
            tmp_path, loader_for=lambda p: VbplArticlesLoader(), embedder=emb, indexer=idx
        )

    r1 = await go()
    _, chunks = idx.docs[rec["id"]]
    assert r1.chunks == len(chunks) >= 3 and chunks[0].chunk.article == "1"
    assert (await go()).skipped == [f.name]
