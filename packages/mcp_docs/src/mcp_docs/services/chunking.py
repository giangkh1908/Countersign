"""Chunking theo heading + cửa sổ token + overlap (module thường, không phải port).

Đếm token: ước lượng `ceil(số_từ_tách_theo_khoảng_trắng * 1.3)`. Tiếng Việt tách theo âm tiết nên
số từ khoảng trắng ~ số âm tiết; SentencePiece của bge-m3 cho ~1.2-1.4 token/âm tiết. Chưa kéo
tokenizer thật vào (gateway không nạp model nặng; docs-mcp cũng không); ước lượng đủ cho
việc đặt ranh giới chunk. Thay bằng tokenizer thật khi có runtime embedding (ghi vào `TOKEN_RATIO`).
"""

from __future__ import annotations

import math
import re

from ..ports.types import Chunk, Document, Section

TOKEN_RATIO = 1.3
MIN_SECTION = 120  # section nhỏ hơn thì gộp với section anh em kế tiếp
TARGET = 500
SOFT_MAX = 600  # section <= SOFT_MAX là 1 chunk
HARD_MAX = 700  # tối đa cứng (bảng/khối không cắt giữa nếu <= HARD_MAX)
OVERLAP = 75  # ~15% của TARGET

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ỵ0-9“\"(])")


def count_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * TOKEN_RATIO)


def embed_text(chunk: Chunk) -> str:
    """Văn bản đem embed = heading + xuống dòng + content (cột `content` giữ nguyên văn)."""
    return f"{chunk.heading}\n{chunk.content}" if chunk.heading else chunk.content


def _hard_cut(sentence: str, limit: int) -> list[str]:
    words = sentence.split()
    step = max(1, int(limit / TOKEN_RATIO))
    return [" ".join(words[i : i + step]) for i in range(0, len(words), step)]


def _split_table(block: str, limit: int) -> list[str]:
    lines = block.split("\n")
    head = lines[:2]
    out: list[str] = []
    cur = list(head)
    for ln in lines[2:]:
        if count_tokens("\n".join([*cur, ln])) > limit and len(cur) > len(head):
            out.append("\n".join(cur))
            cur = list(head)
        cur.append(ln)
    out.append("\n".join(cur))
    return out


def _units(text: str) -> list[str]:
    """Phân rã văn bản dài thành các đơn vị <= SOFT_MAX token: khối (đoạn/bảng) -> câu -> cắt cứng."""
    units: list[str] = []
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        n = count_tokens(block)
        if n <= HARD_MAX and (block.startswith("|") or n <= SOFT_MAX):
            units.append(block)
            continue
        if block.startswith("|"):
            units.extend(_split_table(block, SOFT_MAX))
            continue
        for sent in _SENT_SPLIT.split(block):
            sent = sent.strip()
            if not sent:
                continue
            if count_tokens(sent) > SOFT_MAX:
                units.extend(_hard_cut(sent, SOFT_MAX))
            else:
                units.append(sent)
    return units


def _pack(units: list[str]) -> list[str]:
    """Gom đơn vị tới ~TARGET token, chunk kế bắt đầu bằng đuôi chunk trước (>= OVERLAP token)."""
    chunks: list[str] = []
    i, n = 0, len(units)
    while i < n:
        j, total = i, 0
        while j < n:
            u = count_tokens(units[j])
            if j > i and total + u > SOFT_MAX:
                break
            total += u
            j += 1
            if total >= TARGET:
                break
        chunks.append("\n\n".join(units[i:j]))
        if j >= n:
            break
        # lùi lại để tạo overlap nhưng luôn tiến lên ít nhất 1 đơn vị
        k, acc = j, 0
        while k - 1 > i and acc < OVERLAP:
            k -= 1
            acc += count_tokens(units[k])
        i = k if k > i else j
    return chunks


def _heading(path: tuple[str, ...]) -> str | None:
    return " > ".join(path) if path else None


def _merge_small(sections: list[Section]) -> list[tuple[tuple[str, ...], str]]:
    """Gộp section < MIN_SECTION token với section anh em kế tiếp (cùng cha)."""
    out: list[tuple[tuple[str, ...], str]] = []
    buf: list[Section] = []

    def flush() -> None:
        if not buf:
            return
        if len(buf) == 1:
            out.append((buf[0].path, buf[0].body))
        else:
            parent = buf[0].path[:-1]
            body = "\n\n".join(f"{s.path[-1]}\n{s.body}" if s.path else s.body for s in buf)
            out.append((parent, body))
        buf.clear()

    for s in sections:
        if buf and buf[0].path[:-1] != s.path[:-1]:
            flush()
        buf.append(s)
        if sum(count_tokens(x.body) for x in buf) >= MIN_SECTION:
            flush()
    flush()
    return out


def split(doc: Document) -> list[Chunk]:
    """Tài liệu -> danh sách `Chunk` (ord tăng dần theo thứ tự đọc)."""
    sections = [s for s in doc.sections if s.body.strip()]
    chunks: list[Chunk] = []
    for path, body in _merge_small(sections):
        parts = [body] if count_tokens(body) <= SOFT_MAX else _pack(_units(body))
        for part in parts:
            chunks.append(Chunk(len(chunks), _heading(path), part, count_tokens(part)))
    return chunks
