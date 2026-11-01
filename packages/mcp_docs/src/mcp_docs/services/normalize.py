"""Chuẩn hoá văn bản: NFC, bỏ ký tự điều khiển và zero-width, gộp khoảng trắng.

Dùng cho nội dung, tiêu đề và cả truy vấn lúc search (cùng một hàm để FTS/embedding khớp nhau).
Zero-width cũng là kênh giấu chỉ dẫn nên bị loại ở đây.
"""

from __future__ import annotations

import re
import unicodedata

# U+200B..U+200F, U+2060, U+FEFF, U+202A..U+202E (bidi override), U+2066..U+2069
_INVISIBLE = re.compile("[​-‏⁠﻿‪-‮⁦-⁩]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")


def normalize_text(s: str) -> str:
    """NFC + bỏ control/zero-width; giữ xuống dòng, gộp khoảng trắng ngang, tối đa một dòng trống."""
    s = unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n")
    s = _INVISIBLE.sub("", s)
    s = _CONTROL.sub("", s)
    s = "\n".join(_SPACES.sub(" ", ln).strip() for ln in s.split("\n"))
    return _BLANKS.sub("\n\n", s).strip()


def normalize_query(q: str) -> str:
    """Truy vấn: như `normalize_text` nhưng gộp luôn xuống dòng thành một khoảng trắng."""
    return re.sub(r"\s+", " ", normalize_text(q)).strip()
