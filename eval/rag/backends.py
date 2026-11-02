"""Dựng `DocumentRetriever` cho từng cấu hình: giả (không hạ tầng) hoặc thật (qua factory mcp_docs).

Cấu hình thật được chọn bằng ghi đè `Settings` (docs_use_vector / docs_use_fts /
docs_direct_lookup). Nếu `Settings` hiện tại chưa có các trường đó (hybrid thật chưa nạp vào
docs-mcp) thì báo lỗi rõ thay vì chạy sai: `extra="ignore"` sẽ lặng lẽ nuốt khoá lạ và cho ra
số của cấu hình khác.
"""

from __future__ import annotations

import os
from pathlib import Path

from acme_common.ports import Principal
from mcp_docs.factory import build_article_reader, build_embedder, build_retriever
from mcp_docs.ports import ArticleReader, DocumentRetriever, SearchResult
from mcp_docs.services.acl import AclPolicy
from mcp_docs.services.article_pin import ArticlePinner
from mcp_docs.services.normalize import normalize_query
from mcp_docs.settings import Settings

from .fakes import CorpusFakeRetriever
from .runner import CONFIGS, RetrieverFactory

Override = dict[str, bool | str | int | float]

OVERRIDES: dict[str, Override] = {
    "vector": {"docs_use_vector": True, "docs_use_fts": False, "docs_direct_lookup": "off"},
    "fts": {"docs_use_vector": False, "docs_use_fts": True, "docs_direct_lookup": "off"},
    "hybrid": {"docs_use_vector": True, "docs_use_fts": True, "docs_direct_lookup": "off"},
    "hybrid_direct": {"docs_use_vector": True, "docs_use_fts": True, "docs_direct_lookup": "pin"},
    # FTS với tách từ (DOCS_FTS_MODE=segmented) để so với FTS unaccent
    "fts_segmented": {
        "docs_use_vector": False,
        "docs_use_fts": True,
        "docs_direct_lookup": "off",
        "docs_fts_mode": "segmented",
    },
}


# Biến thể truy xuất (mỗi hậu tố một thay đổi so với cấu hình gốc, ghép bằng "+").
# Tên cấu hình: "<gốc>@<hậu tố>[+<hậu tố>]", ví dụ "hybrid@wfts0.5", "fts@stop".
SUFFIXES: dict[str, Override] = {
    "wfts0.5": {"docs_rrf_weight_fts": 0.5},
    "wfts0.25": {"docs_rrf_weight_fts": 0.25},
    "wfts0.1": {"docs_rrf_weight_fts": 0.1},
    "stop": {"docs_fts_stopwords": True},  # bỏ từ dừng phía truy vấn FTS
    "rank": {"docs_fts_rank": "rank"},  # ts_rank thay ts_rank_cd
    "title": {"docs_fts_title": True},  # tiêu đề văn bản trọng số A, ghép lúc truy vấn
    "nc250": {"docs_n_cand": 250},  # đúng giá trị eval đang dùng (5*pool); dùng khi chẩn đoán
    "nc50": {"docs_n_cand": 50},  # số ứng viên mỗi nhánh (mặc định eval: 5*pool = 250)
    "nc70": {"docs_n_cand": 70},  # giá trị docs-mcp thực dùng: max(50, 5*14)
}

# Nhóm cấu hình cho --configs
GROUPS: dict[str, tuple[str, ...]] = {
    "default": CONFIGS,
    "sweep": (
        *CONFIGS,
        "hybrid@nc50", "hybrid@nc70",
        "hybrid@wfts0.5", "hybrid@wfts0.25", "hybrid@wfts0.1",
        "fts@stop", "hybrid@stop",
        "fts@rank", "hybrid@rank",
        "fts@title", "hybrid@title",
        "hybrid@stop+wfts0.25",
        "hybrid_direct@wfts0.5", "hybrid_direct@wfts0.25", "hybrid_direct@wfts0.1",
        "hybrid_direct@stop", "hybrid_direct@rank", "hybrid_direct@title",
        "hybrid_direct@stop+wfts0.25",
    ),
}  # fmt: skip


def config_overrides(name: str) -> Override:
    """Ghi đè Settings của cấu hình `name` (gốc hoặc gốc@hậu_tố)."""
    base, _, suffix = name.partition("@")
    if base not in OVERRIDES:
        raise UnsupportedConfig(f"cấu hình lạ: {name!r}")
    out: Override = dict(OVERRIDES[base])
    for part in filter(None, suffix.split("+")):
        if part not in SUFFIXES:
            raise UnsupportedConfig(f"hậu tố lạ {part!r} trong {name!r}; có: {sorted(SUFFIXES)}")
        out.update(SUFFIXES[part])
    return out


def parse_configs(spec: str) -> tuple[str, ...]:
    """`default`, `sweep` hoặc danh sách tên cách nhau dấu phẩy."""
    if spec in GROUPS:
        return GROUPS[spec]
    names = tuple(x.strip() for x in spec.split(",") if x.strip())
    for n in names:
        config_overrides(n)
    return names


class UnsupportedConfig(Exception):
    """Settings của docs-mcp chưa có công tắc cần cho cấu hình này."""


class PinningRetriever(DocumentRetriever):
    """Decorator: ghim chunk của "Điều N <văn bản>" lên đầu, cùng `ArticlePinner` và ACL như service."""

    def __init__(self, inner: DocumentRetriever, reader: ArticleReader) -> None:
        self._inner = inner
        self._reader = reader
        self._pinner = ArticlePinner(reader)

    async def search(
        self,
        query: str,
        principal: Principal,
        k: int,
        department_filter: str | None = None,
    ) -> SearchResult:
        res = await self._inner.search(query, principal, k, department_filter)
        pinned, _ = await self._pinner.pin(normalize_query(query), principal)
        pinned = [
            c
            for c in pinned
            if AclPolicy.can_read(principal, c.department, c.classification, c.allowed_roles)
        ]
        if not pinned:
            return res
        ids = {c.chunk_id for c in pinned}
        chunks = [*pinned, *(c for c in res.chunks if c.chunk_id not in ids)]
        return SearchResult(chunks[:k], res.mode)

    async def aclose(self) -> None:
        await self._inner.aclose()
        await self._reader.aclose()


def fake_factory(raw: Path) -> RetrieverFactory:
    def build(config: str) -> DocumentRetriever:
        return CorpusFakeRetriever(raw, config)

    return build


def real_factory(settings: Settings, configs: tuple[str, ...] = CONFIGS) -> RetrieverFactory:
    missing = sorted(
        {k for cfg in configs for k in config_overrides(cfg)} - set(type(settings).model_fields)
    )
    if missing:
        raise UnsupportedConfig(
            "Settings của docs-mcp chưa có "
            + ", ".join(m.upper() for m in missing)
            + ": chưa chạy được 4 cấu hình trên retriever thật (cần hybrid R1). "
            "Dùng --fake để kiểm mạch."
        )

    def build(config: str) -> DocumentRetriever:
        s = Settings(**{**settings.model_dump(), **config_overrides(config)})
        embedder = build_embedder(s.docs_embedder, s)
        retriever = build_retriever(s.docs_retriever, s, embedder=embedder)
        if s.docs_direct_lookup == "pin":
            retriever = PinningRetriever(retriever, build_article_reader(s.docs_retriever, s))
        return retriever

    return build


async def resolve_embed_model(settings: Settings) -> str:
    """Id model thật của embedder đang cấu hình (gọi thăm dò một lần để gateway báo id)."""
    embedder = build_embedder(settings.docs_embedder, settings)
    try:
        await embedder.embed(["probe"])
        return embedder.model_id
    finally:
        await embedder.aclose()


def index_versions(
    settings: Settings, *, fake: bool, index_sig: str | None, embed_model: str | None = None
) -> dict[str, object]:
    """Phiên bản index ghi vào báo cáo. `index_sig` thật do người chạy truyền (CLI/env)."""
    if fake:
        return {"embed_model": "fake_hash", "embed_dim": 256, "index_sig": "fake"}
    return {
        "embed_model": embed_model or settings.docs_embed_model,
        "embed_dim": settings.docs_embed_dim,
        "embedder": settings.docs_embedder,
        "index_sig": index_sig or os.environ.get("DOCS_INDEX_SIG") or "unknown",
    }
