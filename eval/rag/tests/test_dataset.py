"""Trình kiểm nhãn bộ câu hỏi."""

from __future__ import annotations

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
    assert len(qs) >= 30
