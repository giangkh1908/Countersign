"""CLI: `uv run --all-packages python -m eval.attack [--quick] [--configs a,b] [--check]`.

Chạy harness ASR tầng hệ thống trong-process (không mạng, không LLM). Ghi report vào `eval/results/attack/`.
`--check`: thoát 1 nếu ASR harm > 0 ở cấu hình đầy đủ lớp (`full`, `full_block`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .harness import CONFIGS, QUICK, render_tables, run_all, summarize

GATED = ("full", "full_block")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.attack", description=__doc__)
    ap.add_argument("--quick", action="store_true", help="chỉ none, full, full_block")
    ap.add_argument("--configs", help="danh sách cấu hình, phân cách bằng dấu phẩy")
    ap.add_argument("--corpus-dir", default=None)
    ap.add_argument("--out", default="eval/results/attack")
    ap.add_argument(
        "--check", action="store_true", help="fail nếu ASR harm > 0 ở cấu hình đầy đủ lớp"
    )
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    names = (
        list(QUICK) if args.quick else (args.configs.split(",") if args.configs else list(CONFIGS))
    )
    if args.check:
        names = sorted(set(names) | set(GATED), key=list(CONFIGS).index)
    kw = {"corpus_dir": Path(args.corpus_dir)} if args.corpus_dir else {}
    results = asyncio.run(run_all(names, **kw))
    rows = summarize(results)
    print(render_tables(rows))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"asr-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "level": "system (mock LLM chiếm hoàn toàn; ASR tầng LLM chưa đo)",
                "summary": rows,
                "cases": {n: [o.__dict__ for o in outs] for n, outs in results.items()},
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"report: {path}")
    bad = [n for n in GATED if n in rows and rows[n]["harm"] > 0]
    if args.check and bad:
        print(f"FAIL: ASR harm > 0 ở cấu hình {bad}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
