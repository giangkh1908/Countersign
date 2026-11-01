"""Tách toàn văn trang vbpl.vn (dữ liệu flight của Next.js) thành danh sách Điều."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
# Tiêu đề Điều: chấp nhận lỗi gõ có trong văn bản gốc ("Điêu 38.", "Ðiều").
HEADING = re.compile(r"^[ĐÐD]i[eêềệ]u\s+(\d+[a-z]?)\s*\.\s*(.*)$")


def flight_text(html: str) -> str:
    return "".join(json.loads('"' + m.group(1) + '"') for m in PUSH.finditer(html))


def articles(html: str) -> list[dict]:
    """Trả về [{article, heading, chapter, paragraphs}] theo thứ tự trong văn bản.

    Một số Điều trong nguồn bị gắn sai class, nên nhận dạng tiêu đề theo mẫu chữ. Điều đã gặp
    thì bỏ qua lần sau (văn bản sửa đổi có thể trích lại "Điều N." của luật khác).
    """
    soup = BeautifulSoup(flight_text(html), "html.parser")
    out: list[dict] = []
    chapter: str | None = None
    cur: dict | None = None
    seen: set[str] = set()
    for p in soup.find_all("p"):
        cls = " ".join(p.get("class") or [])
        text = re.sub(r"\s+", " ", p.get_text(" ")).strip()
        if not text:
            continue
        m = HEADING.match(text)
        if "prov-chapter" in cls:
            chapter = text if text.lower().startswith("chương") else f"{chapter} - {text}"
        elif m and len(text) < 600 and m.group(1) not in seen:
            seen.add(m.group(1))
            cur = {
                "article": m.group(1),
                "heading": m.group(2),
                "chapter": chapter,
                "paragraphs": [],
            }
            out.append(cur)
        elif cur is not None:
            cur["paragraphs"].append(text)
    return out
