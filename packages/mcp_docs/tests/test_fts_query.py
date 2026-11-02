"""Từ dừng phía truy vấn FTS và các công tắc mới của nhánh FTS/RRF (không cần Postgres)."""

from __future__ import annotations

import pytest
from mcp_docs.adapters.fake_hash import FakeHashEmbedder
from mcp_docs.adapters.pgvector_hybrid import PgVectorHybridRetriever
from mcp_docs.services.fts_query import strip_stopwords
from mcp_docs.settings import Settings


def test_bo_tu_dung_giu_thuat_ngu_va_thu_tu():
    q = "Tôi làm ở công ty 5 năm rồi nghỉ thì trợ cấp thôi việc được tính như thế nào?"
    assert strip_stopwords(q) == "làm ở công ty 5 năm nghỉ trợ cấp thôi việc tính"


def test_phan_biet_dau_khong_bo_nham():
    # "la" (không dấu) không phải từ dừng "là"
    assert strip_stopwords("la hét") == "la hét"


def test_loai_het_thi_tra_lai_goc():
    assert strip_stopwords("và của là") == "và của là"


def _retriever(**kw: object) -> PgVectorHybridRetriever:
    return PgVectorHybridRetriever("postgresql://x", FakeHashEmbedder(dim=8), **kw)  # type: ignore[arg-type]


def test_mac_dinh_giu_hanh_vi_cu():
    s = Settings()
    assert s.docs_rrf_weight_fts == 1.0 and not s.docs_fts_stopwords
    assert s.docs_fts_rank == "cd" and not s.docs_fts_title
    sql = _retriever()._sql
    assert "ts_rank_cd(c.tsv, q.qt, 32)" in sql
    assert "JOIN documents d ON d.id = c.document_id, q" not in sql
    assert "{" not in sql.replace("{}", "")  # không sót placeholder


def test_bien_the_sql():
    assert "ts_rank(c.tsv, q.qt, 32)" in _retriever(fts_rank="rank")._sql
    title = _retriever(fts_title=True)._sql
    assert "setweight(to_tsvector('simple', acme.immutable_unaccent(d.title)), 'A')" in title
    assert "FROM chunks c JOIN documents d ON d.id = c.document_id, q" in title


@pytest.mark.parametrize(
    "kw",
    [
        {"fts_rank": "bm25"},
        {"rrf_weight_fts": -0.1},
        {"fts_title": True, "fts_mode": "segmented"},
    ],
)
def test_tham_so_sai(kw: dict[str, object]):
    with pytest.raises(ValueError):
        _retriever(**kw)
