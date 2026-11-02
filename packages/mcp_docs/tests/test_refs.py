import pytest
from mcp_docs.ports import Ref
from mcp_docs.refs import clause_matches, parse_refs


def test_article_with_law_name() -> None:
    assert parse_refs("Điều 38 Bộ luật Lao động quy định gì?") == [
        Ref("38", None, None, "bo luat lao dong")
    ]


def test_clause_before_and_after_article() -> None:
    assert parse_refs("khoản 2 Điều 38a")[0] == Ref("38a", "2", None, None)
    assert parse_refs("Điều 38 khoản 2 của Luật Doanh nghiệp")[0] == Ref(
        "38", "2", None, "luat doanh nghiep"
    )


def test_doc_number_beats_name_and_is_uppercased() -> None:
    assert parse_refs("điều 5 luật 45/2019/qh14") == [Ref("5", None, "45/2019/QH14", None)]


def test_several_articles_share_document() -> None:
    refs = parse_refs("So sánh Điều 10 và Điều 11 Luật Đất đai")
    assert [r.article for r in refs] == ["10", "11"]
    assert {r.doc_hint for r in refs} == {"luat dat dai"}


@pytest.mark.parametrize(
    "q", ["nghỉ phép năm bao nhiêu ngày", "Luật Lao động 2019", "45/2019/QH14"]
)
def test_no_article_no_refs(q: str) -> None:
    assert parse_refs(q) == []


def test_hint_stops_at_stopword() -> None:
    assert parse_refs("Điều 3 Luật Bảo hiểm xã hội năm 2014")[0].doc_hint == "luat bao hiem xa hoi"


@pytest.mark.parametrize(
    ("label", "clause", "ok"),
    [
        ("2", "2", True),
        ("1-3", "2", True),
        ("1-3", "4", False),
        (None, "1", False),
        ("2", "x", False),
    ],
)
def test_clause_matches(label: str | None, clause: str, ok: bool) -> None:
    assert clause_matches(label, clause) is ok
