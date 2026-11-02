"""Nhận dạng tham chiếu pháp lý trong câu hỏi: "Điều 38", "khoản 2 Điều 38", số hiệu "45/2019/QH14".

Module thường (không phải port). Chỉ phân tích chuỗi, không đụng kho dữ liệu: việc giải tên văn bản
thành số hiệu do `ArticleReader.find_documents` làm.
"""

from __future__ import annotations

import re
import unicodedata

from .ports.types import Ref

_DOC_NUM = re.compile(r"\b(\d{1,4}/\d{4}/[A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
_ARTICLE = re.compile(
    r"(?:khoan\s+(?P<c1>\d+)\s+(?:cua\s+)?)?"
    r"\bdieu\s+(?P<a>\d+[a-z]?)\b"
    r"(?:\s*,?\s*khoan\s+(?P<c2>\d+))?"
)
# tên văn bản: "bo luat X Y" / "luat X Y" (đã bỏ dấu); dừng ở từ không thuộc tên
_HINT = re.compile(r"\b(?:bo\s+luat|luat)\s+(?P<name>(?:[a-z]+\s*){1,5})")
_STOP = frozenset(
    {
        *("nam", "so", "quy", "dinh", "the", "nao", "la", "gi", "co", "khong", "ve", "theo"),
        *("nhu", "nay", "do", "cua", "va", "hay", "hoac", "khi", "neu", "thi", "duoc", "phai"),
        *("nhieu", "nhung", "cac", "mot", "trong", "voi", "cho", "tai", "tu", "den"),
    }
)


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu (đ -> d). Chỉ dùng để so khớp từ khoá, không dùng để hiển thị."""
    t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in t if not unicodedata.combining(c))


def _hint(folded: str) -> str | None:
    m = _HINT.search(folded)
    if not m:
        return None
    words: list[str] = []
    for w in m.group("name").split():
        if w in _STOP:
            break
        words.append(w)
    if not words:
        return None
    kind = "bo luat" if m.group(0).lstrip().startswith("bo") else "luat"
    return f"{kind} {' '.join(words)}"


def parse_refs(query: str) -> list[Ref]:
    """Mỗi lần nhắc "Điều N" thành một `Ref`; số hiệu / tên văn bản đầu tiên trong câu gắn cho tất cả.

    Câu không nêu Điều thì trả danh sách rỗng (nhánh tra trực tiếp không chạy).
    """
    folded = fold(query)
    dm = _DOC_NUM.search(query)
    doc_num = dm.group(1).upper() if dm else None
    hint = None if doc_num else _hint(folded)
    refs: list[Ref] = []
    for m in _ARTICLE.finditer(folded):
        clause = m.group("c1") or m.group("c2")
        refs.append(Ref(m.group("a"), clause, doc_num, hint))
    return refs


def clause_matches(label: str | None, clause: str) -> bool:
    """`label` là nhãn khoản của chunk ("2", "1-3" hoặc None); khớp khi khoản `clause` nằm trong nhãn."""
    if not label or not clause.isdigit():
        return False
    lo, _, hi = label.partition("-")
    try:
        return int(lo) <= int(clause) <= int(hi or lo)
    except ValueError:
        return False
