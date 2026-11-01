from pathlib import Path

from mcp_docs.adapters.markdown import MarkdownLoader
from mcp_docs.ports import Document, Section
from mcp_docs.services.chunking import (
    HARD_MAX,
    MIN_SECTION,
    SOFT_MAX,
    count_tokens,
    embed_text,
    split,
)
from mcp_docs.services.normalize import normalize_query, normalize_text


def words(n: int, prefix: str = "từ") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def doc(*secs: tuple[tuple[str, ...], str]) -> Document:
    return Document("a.md", "A", tuple(Section(p, b) for p, b in secs))


def test_small_section_is_one_chunk_with_heading_path() -> None:
    chunks = split(doc((("Chính sách", "Nghỉ phép"), words(130))))
    assert len(chunks) == 1
    assert chunks[0].heading == "Chính sách > Nghỉ phép" and chunks[0].ord == 0
    assert chunks[0].n_tokens == count_tokens(chunks[0].content)


def test_tiny_siblings_merge_but_not_across_parents() -> None:
    d = doc(
        (("A", "a1"), words(20, "x")),
        (("A", "a2"), words(20, "y")),
        (("B", "b1"), words(20, "z")),
    )
    chunks = split(d)
    assert len(chunks) == 2
    assert chunks[0].heading == "A" and "a1" in chunks[0].content and "a2" in chunks[0].content
    assert chunks[1].heading == "B > b1"


def test_large_section_splits_with_overlap_and_ord_increasing() -> None:
    sent = lambda i: f"Câu số {i} " + words(14, "w") + "."  # noqa: E731
    body = " ".join(sent(i) for i in range(200))
    chunks = split(doc((("Dài",), body)))
    assert len(chunks) > 3
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    assert all(c.n_tokens <= SOFT_MAX + 30 for c in chunks)
    # overlap: câu cuối chunk i xuất hiện lại trong chunk i+1
    for a, b in zip(chunks, chunks[1:], strict=False):
        last = a.content.split("\n\n")[-1]
        assert last in b.content
    # không mất nội dung
    joined = " ".join(c.content for c in chunks)
    assert all(f"Câu số {i} " in joined for i in range(200))


def test_table_not_cut_when_small_and_header_repeated_when_large() -> None:
    small = "\n".join(["| a | b |", "|---|---|", *[f"| {i} | v |" for i in range(10)]])
    assert len(split(doc((("T",), small + "\n\n" + words(130))))) == 1
    rows = [f"| {i} | " + words(10, "c") + " |" for i in range(200)]
    big = "\n".join(["| h1 | h2 |", "|---|---|", *rows])
    chunks = split(doc((("Bảng",), big)))
    assert len(chunks) > 1
    assert all(c.content.startswith("| h1 | h2 |") for c in chunks)


def test_overlong_sentence_is_hard_cut() -> None:
    chunks = split(doc((("L",), words(2000))))
    assert len(chunks) >= 3 and all(c.n_tokens <= HARD_MAX for c in chunks)


def test_empty_sections_skipped_and_embed_text() -> None:
    assert split(doc((("E",), "   "))) == []
    (c,) = split(doc((("H",), words(MIN_SECTION))))
    assert embed_text(c).startswith("H\n") and c.content in embed_text(c)


def test_markdown_loader_sections_and_fences(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text(
        "# Tiêu đề\n\nmở đầu\n\n## Mục 1\n\nnội dung 1\n\n```\n# không phải heading\n```\n\n"
        "### Con\n\nnội dung con\n\n## Mục 2\n\nnội dung 2\n",
        encoding="utf-8",
    )
    d = MarkdownLoader().load(f, source_path="corpus/ALL/x.md")
    assert d.title == "Tiêu đề" and d.source_path == "corpus/ALL/x.md"
    paths = [s.path for s in d.sections]
    assert paths == [
        ("Tiêu đề",),
        ("Tiêu đề", "Mục 1"),
        ("Tiêu đề", "Mục 1", "Con"),
        ("Tiêu đề", "Mục 2"),
    ]
    assert "# không phải heading" in d.sections[1].body


def test_normalize_nfc_and_invisible() -> None:
    nfd = "nghỉ phép"  # dạng NFD (dấu rời)
    assert normalize_text(nfd) == "nghỉ phép"
    assert normalize_text("a​b‮c\x00d") == "abcd"
    assert normalize_query("  a \n\n b\t c ") == "a b c"
