"""Kiểm cấu hình chỉ mục (module thường): chữ ký chỉ mục và thăm dò số chiều của embedder."""

from __future__ import annotations

import hashlib

from ..ports import Embedder, IndexConfigError


def compute_index_sig(
    *,
    chunker_version: str,
    embed_model: str,
    embed_dim: int,
    article_max_tokens: int,
    segmenter: str,
) -> str:
    """Chữ ký chỉ mục: đổi chunker, model, chiều, ngưỡng Điều hoặc bộ tách từ thì tài liệu nạp lại."""
    raw = "|".join(
        [chunker_version, embed_model, str(embed_dim), str(article_max_tokens), segmenter]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def probe_embedder(embedder: Embedder, expected_dim: int) -> None:
    """Gọi embedder một lần và so số chiều. Lỗi gọi (`EmbeddingUnavailable`) cứ lan ra: không suy giảm."""
    vec = (await embedder.embed(["dim probe"]))[0]
    if len(vec) != expected_dim:
        raise IndexConfigError(
            f"embedder trả vector {len(vec)} chiều nhưng DOCS_EMBED_DIM={expected_dim}"
        )
