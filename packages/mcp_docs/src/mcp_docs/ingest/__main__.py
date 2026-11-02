"""CLI: `uv run python -m mcp_docs.ingest [--corpus-dir DIR] [--force]` (đọc cấu hình từ env/.env)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ..factory import build_embedder, build_indexer, build_loader, build_segmenter
from ..ports import (
    DocumentRejected,
    EmbeddingUnavailable,
    IndexConfigError,
    RetrievalUnavailable,
)
from ..settings import Settings
from .job import run_ingest


async def _main(args: argparse.Namespace) -> int:
    s = Settings()
    embedder = build_embedder(s.docs_embedder, s)
    indexer = build_indexer(s.docs_indexer, s)
    try:
        report = await run_ingest(
            Path(args.corpus_dir or s.docs_corpus_dir),
            loader_for=lambda p: build_loader(p, s),
            embedder=embedder,
            indexer=indexer,
            force=args.force,
            article_max_tokens=s.docs_article_max_tokens,
            segmenter=build_segmenter(s.docs_segmenter, s),
            embed_model=s.docs_embed_model,
        )
    except (DocumentRejected, EmbeddingUnavailable, RetrievalUnavailable, IndexConfigError) as e:
        print(f"ingest FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        await embedder.aclose()
        await indexer.aclose()
    print(
        f"ingest OK: embedder={s.docs_embedder} ingested={len(report.ingested)} "
        f"skipped={len(report.skipped)} chunks={report.chunks}"
    )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m mcp_docs.ingest")
    ap.add_argument("--corpus-dir", help="mặc định DOCS_CORPUS_DIR (data/generated)")
    ap.add_argument("--force", action="store_true", help="ingest lại kể cả khi sha256 không đổi")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":  # psycopg async cần SelectorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
