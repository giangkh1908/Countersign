"""Chunking theo heading + cửa sổ token + overlap (module thường, không phải port).

Đếm token: ước lượng `ceil(số_từ_tách_theo_khoảng_trắng * 1.3)`. Tiếng Việt tách theo âm tiết nên
số từ khoảng trắng ~ số âm tiết; SentencePiece của bge-m3 cho ~1.2-1.4 token/âm tiết. Chưa kéo
tokenizer thật vào (gateway không nạp model nặng; docs-mcp cũng không); ước lượng đủ cho
việc đặt ranh giới chunk. Thay bằng tokenizer thật khi có runtime embedding (ghi vào `TOKEN_RATIO`).
"""

from __future__ import annotations

import math
import re

from ..ports.types import ArticleUnit, Chunk, Document, DocumentRejected, Section

TOKEN_RATIO = 1.3
MIN_SECTION = 120  # section nhỏ hơn thì gộp với section anh em kế tiếp
TARGET = 500
SOFT_MAX = 600  # section <= SOFT_MAX là 1 chunk
HARD_MAX = 700  # tối đa cứng (bảng/khối không cắt giữa nếu <= HARD_MAX)
OVERLAP = 75  # ~15% của TARGET
ARTICLE_MAX_TOKENS = 600  # Điều <= ngưỡng này là một chunk (cấu hình DOCS_ARTICLE_MAX_TOKENS)
CHUNKER_VERSION = "article-1"  # tăng tay khi đổi thuật toán chia chunk

_CLAUSE = re.compile(r"^(\d+)\.\s")
_POINT = re.compile(r"^[a-zđ]\)")
_WORD = re.compile(r"\S+")

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ỵ0-9“\"(])")


def count_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * TOKEN_RATIO)


def embed_text(chunk: Chunk, doc_title: str | None = None) -> str:
    """Văn bản đem embed = heading + xuống dòng + content (cột `content` giữ nguyên văn).

    Văn bản luật: truyền `doc_title` để thêm "{tên văn bản} — " vào đầu; heading không lặp lại
    khi `content` đã bắt đầu bằng nó (chunk đầu của Điều chứa tiêu đề Điều).
    """
    body = chunk.content
    if chunk.heading and not body.startswith(chunk.heading):
        body = f"{chunk.heading}\n{body}"
    return f"{doc_title} — {body}" if doc_title else body


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


def split(doc: Document, *, article_max_tokens: int = ARTICLE_MAX_TOKENS) -> list[Chunk]:
    """Tài liệu -> danh sách `Chunk` (ord tăng dần theo thứ tự đọc); rẽ nhánh theo `doc.kind`."""
    if doc.kind == "article":
        return split_articles(doc, article_max_tokens=article_max_tokens)
    sections = [s for s in doc.sections if s.body.strip()]
    chunks: list[Chunk] = []
    for path, body in _merge_small(sections):
        parts = [body] if count_tokens(body) <= SOFT_MAX else _pack(_units(body))
        for part in parts:
            chunks.append(Chunk(len(chunks), _heading(path), part, count_tokens(part)))
    return chunks


# --- Văn bản luật: chia theo Điều / khoản / điểm (rag-citations §1.3) ---

Span = tuple[int, int]


def article_header(unit: ArticleUnit) -> str:
    return f"Điều {unit.article}." + (f" {unit.heading}" if unit.heading else "")


def article_text(unit: ArticleUnit) -> str:
    """Văn bản chuẩn của một Điều, gốc của `char_start/char_end`."""
    header = article_header(unit)
    return header + ("\n" + "\n".join(unit.paragraphs) if unit.paragraphs else "")


def _para_spans(unit: ArticleUnit) -> list[Span]:
    pos = len(article_header(unit)) + 1
    out: list[Span] = []
    for p in unit.paragraphs:
        out.append((pos, pos + len(p)))
        pos += len(p) + 1
    return out


def _word_cut(at: str, s: int, e: int, limit: int) -> list[Span]:
    words = list(_WORD.finditer(at, s, e))
    step = max(1, int(limit / TOKEN_RATIO))
    return [
        (words[i].start(), words[min(i + step, len(words)) - 1].end())
        for i in range(0, len(words), step)
    ]


def _sentence_cut(at: str, s: int, e: int, limit: int) -> list[Span]:
    spans: list[Span] = []
    prev = s
    for m in _SENT_SPLIT.finditer(at, s, e):
        spans.append((prev, m.start()))
        prev = m.end()
    spans.append((prev, e))
    out: list[Span] = []
    for a, b in spans:
        out.extend([(a, b)] if count_tokens(at[a:b]) <= limit else _word_cut(at, a, b, limit))
    return out


def _pieces(at: str, paras: list[Span], s: int, e: int, limit: int) -> list[Span]:
    """Cắt [s, e) thành các khoảng <= limit token: điểm -> đoạn -> câu -> từ."""
    if count_tokens(at[s:e]) <= limit:
        return [(s, e)]
    inside = [p for p in paras if p[0] >= s and p[1] <= e]
    if len(inside) <= 1:
        return _sentence_cut(at, s, e, limit)
    groups: list[list[Span]] = []
    for p in inside:
        if not groups or _POINT.match(at[p[0] : p[1]]):
            groups.append([p])
        else:
            groups[-1].append(p)
    if len(groups) == 1:  # không có điểm: mỗi đoạn một nhóm
        groups = [[p] for p in inside]
    out: list[Span] = []
    for i, g in enumerate(groups):
        gs = s if i == 0 else g[0][0]
        ge = e if i == len(groups) - 1 else g[-1][1]
        out.extend(_pieces(at, paras, gs, ge, limit))
    return out


def _pack_spans(at: str, pieces: list[Span]) -> list[Span]:
    """Gom các khoảng liền kề tới ~TARGET token, không vượt SOFT_MAX, không overlap."""
    out: list[Span] = []
    cs, ce = pieces[0]
    for ns, ne in pieces[1:]:
        if count_tokens(at[cs:ce]) < TARGET and count_tokens(at[cs:ne]) <= SOFT_MAX:
            ce = ne
        else:
            out.append((cs, ce))
            cs, ce = ns, ne
    out.append((cs, ce))
    return out


def _clause_label(nums: list[int]) -> str | None:
    if not nums:
        return None
    return str(nums[0]) if nums[0] == nums[-1] else f"{nums[0]}-{nums[-1]}"


def _article_groups(at: str, unit: ArticleUnit, paras: list[Span]) -> list[tuple[list[int], Span]]:
    """Phần dẫn + từng khoản, rồi gộp khoản nhỏ liền kề -> [(số khoản, khoảng)]."""
    lead_end = len(article_header(unit))
    clauses: list[list[int]] = []  # [số khoản, start, end]
    expected = 1
    for (ps, pe), text in zip(paras, unit.paragraphs, strict=True):
        m = _CLAUSE.match(text)
        if m and int(m.group(1)) == expected:
            clauses.append([expected, ps, pe])
            expected += 1
        elif clauses:
            clauses[-1][2] = pe
        else:
            lead_end = pe
    units: list[tuple[int | None, int, int]] = [(None, 0, lead_end)]
    units += [(n, a, b) for n, a, b in clauses]
    groups: list[tuple[list[int], Span]] = []
    i = 0
    while i < len(units):
        n, a, b = units[i]
        nums = [n] if n is not None else []
        i += 1
        while i < len(units):
            nn, na, nb = units[i]
            cur_t, nxt_t = count_tokens(at[a:b]), count_tokens(at[na:nb])
            small = cur_t < MIN_SECTION or nxt_t < MIN_SECTION
            # phần dẫn nhỏ luôn gộp vào khoản 1 (kể cả khoản 1 sẽ bị cắt tiếp) để không có chunk chỉ gồm tiêu đề
            lead_small = n is None and cur_t < MIN_SECTION and not nums
            if lead_small or (cur_t < TARGET and small and count_tokens(at[a:nb]) <= HARD_MAX):
                b = nb
                nums.append(nn)  # type: ignore[arg-type]  # đơn vị sau phần dẫn luôn có số khoản
                i += 1
            else:
                break
        groups.append((nums, (a, b)))
    return groups


def split_articles(doc: Document, *, article_max_tokens: int = ARTICLE_MAX_TOKENS) -> list[Chunk]:
    """Văn bản luật -> chunk theo Điều; Điều dài cắt theo khoản, điểm, câu. Tất định, không overlap."""
    chunks: list[Chunk] = []
    for sec in doc.sections:
        unit = sec.unit
        if unit is None or not unit.article.strip():
            raise DocumentRejected(f"{doc.source_path}: section without article unit")
        at = article_text(unit)
        header = article_header(unit)
        spans: list[tuple[Span, str | None]]
        if count_tokens(at) <= article_max_tokens:
            spans = [((0, len(at)), None)]
        else:
            paras = _para_spans(unit)
            spans = []
            for nums, (a, b) in _article_groups(at, unit, paras):
                label = _clause_label(nums)
                if count_tokens(at[a:b]) <= HARD_MAX:
                    spans.append(((a, b), label))
                else:
                    spans += [
                        (sp, label) for sp in _pack_spans(at, _pieces(at, paras, a, b, SOFT_MAX))
                    ]
        for (a, b), clause in spans:
            content = at[a:b]
            chunks.append(
                Chunk(
                    len(chunks),
                    header,
                    content,
                    count_tokens(content),
                    unit.article,
                    clause,
                    unit.chapter,
                    a,
                    b,
                )
            )
    return chunks
