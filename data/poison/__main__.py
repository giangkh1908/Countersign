"""CLI: `uv run python -m data.poison [--out DIR]` sinh lại corpus độc (xoá và ghi đè `--out`).

Nạp vào kho tri thức (cần stack chạy, KHÔNG tự động):
`uv run python -m mcp_docs.ingest --corpus-dir data/corpus` (hoặc `bash scripts/ingest-attack-corpus.sh`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import DEFAULT_OUT, build


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m data.poison", description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="thư mục đầu ra (mặc định data/corpus)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    summary = build(Path(args.out))
    print(f"corpus độc: {summary['documents']} tài liệu -> {args.out}")
    for k, n in sorted(summary["by_technique"].items()):
        print(f"  {k}: {n}")


if __name__ == "__main__":
    main()
