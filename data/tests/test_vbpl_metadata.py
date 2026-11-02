"""selection.json (tên văn bản) và documents.jsonl của corpus luật."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.vbpl.metadata import GROUP_ACL, build_metadata, slug_of

SELECTION = json.loads(
    (Path(__file__).parents[1] / "vbpl" / "selection.json").read_text(encoding="utf-8")
)


def test_selection_has_19_unique_titled_documents() -> None:
    assert len(SELECTION) == 19
    assert len({s["doc_num"] for s in SELECTION}) == 19
    assert all(s["title"].strip() for s in SELECTION)


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    for s in SELECTION:
        (tmp_path / f"{slug_of(s['doc_num'])}.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_metadata_acl_mapping_and_fields(raw: Path) -> None:
    rows = build_metadata(raw)
    assert len(rows) == 19 and len({r["id"] for r in rows}) == 19
    by = {r["doc_num"]: r for r in rows}
    assert (by["45/2019/QH14"]["department"], by["45/2019/QH14"]["classification"]) == ("HR", 1)
    assert (by["116/2025/QH15"]["department"], by["116/2025/QH15"]["classification"]) == ("IT", 1)
    assert (by["88/2015/QH13"]["department"], by["88/2015/QH13"]["classification"]) == ("ALL", 0)
    assert (by["59/2020/QH14"]["department"], by["59/2020/QH14"]["classification"]) == ("ALL", 0)
    r = by["45/2019/QH14"]
    assert r["source_path"] == "45-2019-qh14.json" and r["kind"] == "van_ban_phap_luat"
    assert r["allowed_roles"] == [] and r["owner_sub"] is None and len(r["sha256"]) == 64


def test_metadata_deterministic_and_parse_meta_accepts(raw: Path) -> None:
    from mcp_docs.ingest.job import parse_meta

    assert build_metadata(raw) == build_metadata(raw)
    for r in build_metadata(raw):
        assert parse_meta(r).doc_num == r["doc_num"]


def test_unknown_group_is_error(raw: Path) -> None:
    sel = [{"doc_num": "45/2019/QH14", "title": "X", "group": "ops", "url": ""}]
    with pytest.raises(ValueError, match="nhóm lạ"):
        build_metadata(raw, sel)
    assert set(GROUP_ACL) == {"hr", "it", "finance", "legal"}
