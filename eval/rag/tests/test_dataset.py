"""Trình kiểm nhãn bộ câu hỏi."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from eval.rag import dataset


def _row(qid: str, doc: str, art: str, **kw) -> dict:
    return {
        "id": qid,
        "question": "Nghỉ phép bao nhiêu ngày?",
        "gold": [{"doc_num": doc, "article": art}],
        **kw,
    }


def test_hop_le(raw: Path, tmp_path: Path, write_suite):
    p = write_suite(
        tmp_path / "s.jsonl", [_row("q1", "45/2019/QH14", "113"), _row("q2", "20/2023/QH15", "23")]
    )
    qs = dataset.load_questions(p)
    assert dataset.validate_questions(qs, raw) == []
    assert [q.gold for q in qs] == [(("45/2019/QH14", "113"),), (("20/2023/QH15", "23"),)]


def test_dieu_khong_ton_tai(raw: Path, tmp_path: Path, write_suite):
    p = write_suite(tmp_path / "s.jsonl", [_row("q1", "45/2019/QH14", "999")])
    errors = dataset.validate_questions(dataset.load_questions(p), raw)
    assert errors == ["q1: không có Điều 999 trong 45/2019/QH14"]


def test_van_ban_khong_ton_tai(raw: Path, tmp_path: Path, write_suite):
    p = write_suite(tmp_path / "s.jsonl", [_row("q1", "1/2000/QH1", "1")])
    errors = dataset.validate_questions(dataset.load_questions(p), raw)
    assert errors == ["q1: văn bản 1/2000/QH1 không có trong corpus"]


def test_id_trung(raw: Path, tmp_path: Path, write_suite):
    p = write_suite(
        tmp_path / "s.jsonl", [_row("q1", "45/2019/QH14", "113"), _row("q1", "45/2019/QH14", "46")]
    )
    errors = dataset.validate_questions(dataset.load_questions(p), raw)
    assert any("id trùng" in e for e in errors)


def test_cau_co_dap_an_ma_gold_rong(raw: Path, tmp_path: Path, write_suite):
    row = {"id": "q1", "question": "Hỏi gì đó?", "gold": []}
    errors = dataset.validate_questions(
        dataset.load_questions(write_suite(tmp_path / "s.jsonl", [row])), raw
    )
    assert errors == ["q1: câu có đáp án nhưng gold rỗng"]


def test_cau_khong_dap_an_hop_le(raw: Path, tmp_path: Path, write_suite):
    row = {
        "id": "q1",
        "question": "Hỏi gì đó?",
        "type": "unanswerable",
        "answerable": False,
        "gold": [],
    }
    assert (
        dataset.validate_questions(
            dataset.load_questions(write_suite(tmp_path / "s.jsonl", [row])), raw
        )
        == []
    )


def test_dong_hong_bao_loi_kem_so_dong(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"id": "q1"}\n', encoding="utf-8")
    with pytest.raises(dataset.DatasetError, match=":1:"):
        dataset.load_questions(p)


def test_thieu_manifest(tmp_path: Path):
    with pytest.raises(dataset.DatasetError, match="manifest"):
        dataset.validate_questions([], tmp_path)


def test_raw_dir_theo_bien_moi_truong(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(dataset.RAW_DIR_ENV, str(tmp_path))
    assert dataset.raw_dir() == tmp_path
    assert dataset.raw_dir("x") == Path("x")


def test_resolve_suite():
    assert dataset.resolve_suite("vbpl-v1") == dataset.SUITE_DIR / "vbpl-v1.jsonl"
    assert dataset.resolve_suite("a/b.jsonl") == Path("a/b.jsonl")


def test_bo_vbpl_v1_hop_le_voi_corpus_that():
    raw = dataset.raw_dir()
    if not (raw / "manifest.json").is_file():
        pytest.skip(f"không có corpus thô tại {raw} (đặt {dataset.RAW_DIR_ENV})")
    qs = dataset.load_questions(dataset.resolve_suite("vbpl-v1"))
    assert dataset.validate_questions(qs, raw) == []
    assert len(qs) == 150


def test_split_va_authoring_mac_dinh_la_dev_read_first(raw: Path, tmp_path: Path, write_suite):
    [q] = dataset.load_questions(
        write_suite(tmp_path / "s.jsonl", [_row("q1", "45/2019/QH14", "113")])
    )
    assert (q.split, q.authoring) == ("dev", "read_first")


def test_split_hoac_authoring_sai_bi_bao_loi(raw: Path, tmp_path: Path, write_suite):
    p = write_suite(
        tmp_path / "s.jsonl",
        [
            _row("q1", "45/2019/QH14", "113", split="validation"),
            _row("q2", "45/2019/QH14", "46", authoring="memory"),
        ],
    )
    errors = dataset.validate_questions(dataset.load_questions(p), raw)
    assert errors == [
        "q1: split 'validation' không thuộc ('dev', 'test')",
        "q2: authoring 'memory' không thuộc ('read_first', 'blind')",
    ]


def test_type_phai_khop_answerable(raw: Path, tmp_path: Path, write_suite):
    p = write_suite(
        tmp_path / "s.jsonl",
        [
            {"id": "q1", "question": "x", "type": "unanswerable", "gold": []},
            {"id": "q2", "question": "y", "answerable": False, "gold": []},
        ],
    )
    errors = dataset.validate_questions(dataset.load_questions(p), raw)
    assert "q1: type 'unanswerable' không khớp answerable=True" in errors
    assert "q2: type 'lookup' không khớp answerable=False" in errors


def test_lookup_nhieu_gold_thay_the_nhau_la_hop_le(raw: Path, tmp_path: Path, write_suite):
    row = _row("q1", "45/2019/QH14", "113")
    row["gold"].append({"doc_num": "45/2019/QH14", "article": "46"})
    qs = dataset.load_questions(write_suite(tmp_path / "s.jsonl", [row]))
    assert dataset.validate_questions(qs, raw) == []
    assert len(qs[0].gold) == 2 and qs[0].type == "lookup"


def test_select_split():
    qs = [
        dataset.Question("a", "x", (("d", "1"),), split="dev"),
        dataset.Question("b", "y", (("d", "2"),), split="test"),
    ]
    assert [q.id for q in dataset.select_split(qs, "test")] == ["b"]
    assert [q.id for q in dataset.select_split(qs, "dev")] == ["a"]
    with pytest.raises(dataset.DatasetError):
        dataset.select_split(qs, "all")


def test_distribution_co_nhom_split_va_cach_viet():
    qs = [
        dataset.Question("a", "x", (("d", "1"),), group="hr", split="dev"),
        dataset.Question(
            "b",
            "y",
            (),
            type="unanswerable",
            answerable=False,
            group="it",
            split="test",
            authoring="blind",
        ),  # fmt: skip
    ]
    d = dataset.distribution(qs)
    assert d["group"] == {"hr": 1, "it": 1} and d["split"] == {"dev": 1, "test": 1}
    assert d["authoring"] == {"blind": 1, "read_first": 1}
    assert d["type"] == {"lookup": 1, "unanswerable": 1} and d["doc_num"] == {"d": 1}


def test_bo_vbpl_v1_cau_truc_khong_can_corpus():
    """Bộ 150 câu: 40 cũ viết sau khi đọc Điều + 110 viết mù, chia dev/test cố định."""
    qs = dataset.load_questions(dataset.resolve_suite("vbpl-v1"))
    assert len({q.id for q in qs}) == len(qs) == 150
    old = [q for q in qs if q.authoring == "read_first"]
    blind = [q for q in qs if q.authoring == "blind"]
    assert len(old) == 40 and len(blind) == 110
    assert all(q.split == "dev" for q in old)  # 40 câu cũ chỉ dùng để chỉnh
    assert Counter(q.split for q in blind) == {"dev": 50, "test": 60}
    assert Counter(q.type for q in blind) == {"lookup": 61, "synthesis": 29, "unanswerable": 20}
    for q in qs:
        assert (q.type == "unanswerable") == (not q.gold)
        if q.type == "synthesis":
            assert len(q.gold) >= 2


def test_cau_blind_nguyen_van_phase1():
    """Câu hỏi viết trước khi mở corpus (phase1) không bị sửa sau khi gán nhãn."""
    path = dataset.SUITE_DIR / "vbpl-v1.phase1.jsonl"
    phase1 = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        phase1[row["id"]] = row["question"]
    for q in dataset.load_questions(dataset.resolve_suite("vbpl-v1")):
        if q.authoring == "blind":
            assert phase1[q.id] == q.question, q.id
