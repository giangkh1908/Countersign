"""Bộ câu hỏi có nhãn (`*.jsonl`) và trình kiểm nhãn so với corpus thô `data/raw/vbpl`.

Mỗi dòng JSON: `id`, `question`, `gold` = [{"doc_num", "article"}, ...] (+ `type`, `group`,
`answerable`, `names_article`). Trình kiểm không đoán gì: mỗi `(doc_num, article)` phải có thật
trong file `<số hiệu>.json` của corpus, `id` không trùng, câu hỏi không rỗng.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEFAULT_RAW_DIR = "data/raw/vbpl"
RAW_DIR_ENV = "VBPL_RAW_DIR"
SUITE_DIR = Path(__file__).parent
TYPES = ("lookup", "synthesis", "unanswerable")


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    question: str
    gold: tuple[tuple[str, str], ...]  # (doc_num, article)
    type: str = "lookup"
    group: str | None = None
    answerable: bool = True
    names_article: bool = False


class DatasetError(Exception):
    """File câu hỏi sai định dạng (không phải lỗi nhãn; lỗi nhãn do `validate_questions` trả về)."""


def raw_dir(override: str | os.PathLike[str] | None = None) -> Path:
    return Path(override or os.environ.get(RAW_DIR_ENV) or DEFAULT_RAW_DIR)


def resolve_suite(suite: str) -> Path:
    """`vbpl-v1` => eval/rag/vbpl-v1.jsonl; chuỗi có đuôi hoặc dấu phân cách thì coi là đường dẫn."""
    p = Path(suite)
    if p.suffix or p.parent != Path("."):
        return p
    return SUITE_DIR / f"{suite}.jsonl"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_questions(path: str | os.PathLike[str]) -> list[Question]:
    out: list[Question] = []
    with open(path, encoding="utf-8") as f:
        for no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                gold = tuple((str(g["doc_num"]), str(g["article"])) for g in row.get("gold", []))
                out.append(
                    Question(
                        id=str(row["id"]),
                        question=str(row["question"]),
                        gold=gold,
                        type=str(row.get("type", "lookup")),
                        group=row.get("group"),
                        answerable=bool(row.get("answerable", True)),
                        names_article=bool(row.get("names_article", False)),
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                raise DatasetError(f"{path}:{no}: dòng không hợp lệ ({e!r})") from e
    return out


def article_file(raw: Path, doc_num: str) -> Path:
    """`45/2019/QH14` => `45-2019-qh14.json`."""
    return raw / f"{doc_num.replace('/', '-').lower()}.json"


def load_articles(raw: Path) -> dict[str, set[str]]:
    """doc_num => tập số Điều có thật, đọc từ manifest.json và các file JSON Điều."""
    manifest = raw / "manifest.json"
    if not manifest.is_file():
        raise DatasetError(f"không có {manifest} (đặt {RAW_DIR_ENV} trỏ tới data/raw/vbpl)")
    docs: dict[str, set[str]] = {}
    for item in json.loads(manifest.read_text(encoding="utf-8")):
        doc_num = item["doc_num"]
        f = article_file(raw, doc_num)
        if not f.is_file():
            raise DatasetError(f"manifest có {doc_num} nhưng thiếu {f}")
        docs[doc_num] = {str(a["article"]) for a in json.loads(f.read_text(encoding="utf-8"))}
    return docs


def validate_questions(questions: list[Question], raw: Path) -> list[str]:
    """Trả danh sách lỗi (rỗng = hợp lệ)."""
    corpus = load_articles(raw)
    errors: list[str] = []
    for qid, n in Counter(q.id for q in questions).items():
        if n > 1:
            errors.append(f"{qid}: id trùng ({n} lần)")
    for q in questions:
        if not q.question.strip():
            errors.append(f"{q.id}: câu hỏi rỗng")
        if q.type not in TYPES:
            errors.append(f"{q.id}: type {q.type!r} không thuộc {TYPES}")
        if q.answerable and not q.gold:
            errors.append(f"{q.id}: câu có đáp án nhưng gold rỗng")
        if not q.answerable and q.gold:
            errors.append(f"{q.id}: câu không có đáp án nhưng có gold")
        if q.type == "synthesis" and len(q.gold) < 2:
            errors.append(f"{q.id}: synthesis cần gold >= 2")
        if len(set(q.gold)) != len(q.gold):
            errors.append(f"{q.id}: gold lặp")
        for doc_num, article in q.gold:
            if doc_num not in corpus:
                errors.append(f"{q.id}: văn bản {doc_num} không có trong corpus")
            elif article not in corpus[doc_num]:
                errors.append(f"{q.id}: không có Điều {article} trong {doc_num}")
    return errors


def distribution(questions: list[Question]) -> dict[str, dict[str, int]]:
    """Số câu theo văn bản (tính mỗi gold) và theo loại, để báo cáo."""
    by_doc = Counter(d for q in questions for d, _ in q.gold)
    by_type = Counter(q.type for q in questions)
    return {"doc_num": dict(sorted(by_doc.items())), "type": dict(by_type)}
