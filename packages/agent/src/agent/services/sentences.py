"""Tách câu cho bộ kiểm chứng (rag-citations §5.3 bước 1). Hàm thuần, không phải port.

Offset `start/end` tính theo điểm mã Unicode trong chính văn bản đầu vào. Dòng (xuống dòng) luôn là ranh
giới; mã trích `[n]` ngay sau dấu chấm câu thuộc về câu đứng trước.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_END = re.compile(r"[.!?…]+(?:\s*\[\d+\])*")
_CITE = re.compile(r"\[(\d+)\]")
_BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)]|[a-zđ][.)])\s+")
# "Điều 38.", "khoản 2.", "điểm a." ... không phải cuối câu
_REF_TAIL = re.compile(r"(?i)(?:^|\s)(?:điều|khoản|điểm|mục|chương|phần|số)\s+[\dIVXLa-zđ]{1,6}$")
_NOT_CLAIM = re.compile(
    r"(?i)^(?:xin chào|chào|cảm ơn|rất tiếc|xin lỗi|không tìm thấy|tôi không (?:tìm thấy|có thông tin))"
)


@dataclass
class Sentence:
    id: int
    start: int
    end: int
    text: str  # văn bản câu bỏ ký hiệu danh sách đầu dòng, giữ mã [n]
    cites: list[int] = field(default_factory=list)
    claim: bool = True


def _starts_new_sentence(ch: str) -> bool:
    return ch.isupper() or ch.isdigit() or ch in '“"('


def _is_claim(body: str) -> bool:
    plain = _CITE.sub("", body).strip()
    if plain.endswith(":") or _NOT_CLAIM.match(plain):
        return False
    return len(re.findall(r"\w+", plain)) >= 3


def split_sentences(text: str) -> list[Sentence]:
    out: list[Sentence] = []
    for line in re.finditer(r"[^\n]+", text):
        raw, base = line.group(0), line.start()
        lead = len(raw) - len(raw.lstrip())
        pos = lead  # đầu câu hiện tại (vị trí trong dòng)
        bullet = _BULLET.match(raw)
        body_from = bullet.end() if bullet else lead
        cuts: list[int] = []
        for m in _END.finditer(raw, body_from):
            tail = raw[m.end() :]
            if tail.strip() == "":
                continue  # cuối dòng, xử lý ở dưới
            if not (tail[0].isspace() and _starts_new_sentence(tail.lstrip()[0])):
                continue
            if _REF_TAIL.search(raw[body_from : m.start()]) and not _CITE.search(m.group(0)):
                continue
            cuts.append(m.end())
        cuts.append(len(raw.rstrip()))
        for cut in cuts:
            seg_raw = raw[pos:cut]
            if seg_raw.strip():
                s0 = pos + (len(seg_raw) - len(seg_raw.lstrip()))
                body = raw[max(s0, body_from) if pos == lead else s0 : cut].strip()
                out.append(
                    Sentence(
                        id=len(out),
                        start=base + s0,
                        end=base + cut,
                        text=body,
                        cites=[int(c) for c in dict.fromkeys(_CITE.findall(body))],
                        claim=_is_claim(body),
                    )
                )
            pos = cut + (len(raw[cut:]) - len(raw[cut:].lstrip()))
    return out
