"""Retriever giả dựng từ corpus thô, để chạy khung đánh giá không cần Postgres/gateway.

Số đo từ đây vô nghĩa (báo cáo ghi `fake: true`); mục đích duy nhất là kiểm mạch: đọc câu hỏi,
gọi port `DocumentRetriever`, chấm điểm, ghi báo cáo. Bốn chế độ phản ánh bốn cấu hình thật:
`vector`, `fts`, `hybrid` (RRF), `hybrid_direct` (thêm tra cứu trực tiếp khi câu nêu số hiệu và Điều).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from acme_common.ports import Principal
from mcp_docs.adapters.fake_hash import FakeHashEmbedder
from mcp_docs.ports import DocumentRetriever, RetrievedChunk, SearchResult

from .dataset import article_file, load_articles

_WORD = re.compile(r"\w+", re.UNICODE)
_ARTICLE_REF = re.compile(r"\bđiều\s+(\d+[a-z]?)\b", re.IGNORECASE)
_DOC_REF = re.compile(r"\b\d+/\d{4}/[A-Za-z0-9\-]+\b")
_DIM = 256
_RRF_K = 60


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in t if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return _WORD.findall(_fold(text))


def eval_principal() -> Principal:
    """Principal đánh giá: thấy mọi phòng ban và mức mật (đo chất lượng truy xuất, không đo ACL)."""
    return Principal(
        sub="eval-rag",
        audience=("docs-mcp",),
        azp="eval-rag",
        scopes=frozenset(),
        expires_at=float("inf"),
        dept=("ALL", "HR", "IT", "SALES"),
        clearance=3,
        roles=(),
    )


class CorpusFakeRetriever(DocumentRetriever):
    """Mỗi Điều là một chunk. `mode` thuộc CONFIGS của runner."""

    def __init__(self, raw: Path, mode: str) -> None:
        if mode not in ("vector", "fts", "fts_segmented", "hybrid", "hybrid_direct"):
            raise ValueError(f"mode lạ: {mode}")
        self.mode = mode
        self._embedder = FakeHashEmbedder(dim=_DIM)
        self._chunks: list[RetrievedChunk] = []
        self._vecs: list[list[float]] = []
        self._tf: list[Counter[str]] = []
        self._df: Counter[str] = Counter()
        self._index: dict[tuple[str, str], int] = {}
        self._load(raw)

    def _load(self, raw: Path) -> None:
        texts: list[str] = []
        for doc_num in sorted(load_articles(raw)):
            data = json.loads(article_file(raw, doc_num).read_text(encoding="utf-8"))
            for a in data:
                content = "\n".join(a["paragraphs"])
                i = len(self._chunks)
                self._index[(doc_num, str(a["article"]))] = i
                self._chunks.append(
                    RetrievedChunk(
                        chunk_id=i,
                        doc_id=doc_num,
                        title=doc_num,
                        heading=a["heading"],
                        source=f"{doc_num}#{a['article']}",
                        ord=int(re.sub(r"\D", "", str(a["article"])) or 0),
                        department="ALL",
                        classification=0,
                        allowed_roles=(),
                        content=content,
                        doc_num=doc_num,
                        article=str(a["article"]),
                    )
                )
                texts.append(f"{a['heading']}\n{content}")
        for t in texts:
            tf = Counter(_tokens(t))
            self._tf.append(tf)
            self._df.update(tf.keys())
        # Embedding giả tất định, tính đồng bộ một lần.
        self._vecs = [self._embedder._one(t) for t in texts]

    def _rank_vector(self, query: str) -> list[int]:
        q = self._embedder._one(query)
        scores = [sum(a * b for a, b in zip(q, v, strict=True)) for v in self._vecs]
        return sorted(range(len(scores)), key=lambda i: (-scores[i], i))

    def _rank_fts(self, query: str) -> list[int]:
        q = set(_tokens(query))
        n = len(self._chunks)
        scores = [
            sum(math.log(1 + n / self._df[w]) * (1 + math.log(tf[w])) for w in q if tf[w] > 0)
            for tf in self._tf
        ]
        return sorted(range(n), key=lambda i: (-scores[i], i))

    def _direct(self, query: str) -> list[int]:
        docs = _DOC_REF.findall(query)
        arts = _ARTICLE_REF.findall(query)
        keys = [(d.upper(), a.lower()) for d in docs for a in arts]
        return [self._index[key] for key in keys if key in self._index]

    async def search(
        self,
        query: str,
        principal: Principal,
        k: int,
        department_filter: str | None = None,
    ) -> SearchResult:
        pool = max(k, 100)
        if self.mode == "vector":
            order = self._rank_vector(query)[:pool]
        elif self.mode in ("fts", "fts_segmented"):
            order = self._rank_fts(query)[:pool]
        else:
            fused: Counter[int] = Counter()
            for ranking in (self._rank_vector(query)[:pool], self._rank_fts(query)[:pool]):
                for rank, i in enumerate(ranking, start=1):
                    fused[i] += 1.0 / (_RRF_K + rank)
            order = sorted(fused, key=lambda i: (-fused[i], i))
            if self.mode == "hybrid_direct":
                direct = self._direct(query)
                order = direct + [i for i in order if i not in direct]
        return SearchResult([self._chunks[i] for i in order[:k]], self.mode)
