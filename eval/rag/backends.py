"""Dựng `DocumentRetriever` cho từng cấu hình: giả (không hạ tầng) hoặc thật (qua factory mcp_docs).

Cấu hình thật được chọn bằng ghi đè `Settings` (docs_use_vector / docs_use_fts /
docs_direct_lookup). Nếu `Settings` hiện tại chưa có các trường đó (hybrid thật chưa nạp vào
docs-mcp) thì báo lỗi rõ thay vì chạy sai: `extra="ignore"` sẽ lặng lẽ nuốt khoá lạ và cho ra
số của cấu hình khác.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp_docs.factory import build_embedder, build_retriever
from mcp_docs.ports import DocumentRetriever
from mcp_docs.settings import Settings

from .fakes import CorpusFakeRetriever
from .runner import CONFIGS, RetrieverFactory

OVERRIDES: dict[str, dict[str, bool]] = {
    "vector": {"docs_use_vector": True, "docs_use_fts": False, "docs_direct_lookup": False},
    "fts": {"docs_use_vector": False, "docs_use_fts": True, "docs_direct_lookup": False},
    "hybrid": {"docs_use_vector": True, "docs_use_fts": True, "docs_direct_lookup": False},
    "hybrid_direct": {"docs_use_vector": True, "docs_use_fts": True, "docs_direct_lookup": True},
}


class UnsupportedConfig(Exception):
    """Settings của docs-mcp chưa có công tắc cần cho cấu hình này."""


def fake_factory(raw: Path) -> RetrieverFactory:
    def build(config: str) -> DocumentRetriever:
        return CorpusFakeRetriever(raw, config)

    return build


def real_factory(settings: Settings) -> RetrieverFactory:
    missing = sorted(
        {k for cfg in CONFIGS for k in OVERRIDES[cfg]} - set(type(settings).model_fields)
    )
    if missing:
        raise UnsupportedConfig(
            "Settings của docs-mcp chưa có "
            + ", ".join(m.upper() for m in missing)
            + ": chưa chạy được 4 cấu hình trên retriever thật (cần hybrid R1). "
            "Dùng --fake để kiểm mạch."
        )

    def build(config: str) -> DocumentRetriever:
        s = Settings(**{**settings.model_dump(), **OVERRIDES[config]})
        embedder = build_embedder(s.docs_embedder, s)
        return build_retriever(s.docs_retriever, s, embedder=embedder)

    return build


def index_versions(settings: Settings, *, fake: bool, index_sig: str | None) -> dict[str, object]:
    """Phiên bản index ghi vào báo cáo. `index_sig` thật do người chạy truyền (CLI/env)."""
    if fake:
        return {"embed_model": "fake_hash", "embed_dim": 256, "index_sig": "fake"}
    return {
        "embed_model": settings.docs_embed_model,
        "embed_dim": settings.docs_embed_dim,
        "embedder": settings.docs_embedder,
        "index_sig": index_sig or os.environ.get("DOCS_INDEX_SIG") or "unknown",
    }
