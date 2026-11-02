"""Corpus thô nhỏ dựng trong thư mục tạm, cùng định dạng `data/raw/vbpl`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DOCS = {
    "45/2019/QH14": [
        {
            "article": "113",
            "heading": "Nghỉ hằng năm",
            "paragraphs": ["Người lao động nghỉ phép năm 12 ngày."],
        },
        {
            "article": "46",
            "heading": "Trợ cấp thôi việc",
            "paragraphs": ["Mỗi năm làm việc được nửa tháng lương."],
        },
    ],
    "20/2023/QH15": [
        {
            "article": "23",
            "heading": "Giá trị pháp lý của chữ ký điện tử",
            "paragraphs": ["Chữ ký số có giá trị như chữ ký tay."],
        },
    ],
}


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    d = tmp_path / "vbpl"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps([{"doc_num": n, "group": "hr", "articles": len(a)} for n, a in DOCS.items()]),
        encoding="utf-8",
    )
    for num, arts in DOCS.items():
        (d / f"{num.replace('/', '-').lower()}.json").write_text(
            json.dumps(arts, ensure_ascii=False), encoding="utf-8"
        )
    return d


@pytest.fixture
def write_suite():
    def write(path: Path, rows: list[dict]) -> Path:
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        path.write_text(text, encoding="utf-8")
        return path

    return write
