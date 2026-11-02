"""CLI: `uv run --all-packages python -m eval.rag {validate,run} --suite vbpl-v1 [...]`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .backends import UnsupportedConfig
from .dataset import (
    DatasetError,
    distribution,
    load_questions,
    raw_dir,
    resolve_suite,
    sha256_file,
    validate_questions,
)

DEFAULT_OUT = "eval/results/rag"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m eval.rag", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in (
        ("validate", "kiểm nhãn so với corpus"),
        ("run", "chạy truy xuất 4 cấu hình"),
    ):
        s = sub.add_parser(name, help=help_)
        s.add_argument(
            "--suite", default="vbpl-v1", help="tên suite (eval/rag/<tên>.jsonl) hoặc đường dẫn"
        )
        s.add_argument("--raw-dir", default=None, help="mặc định $VBPL_RAW_DIR hoặc data/raw/vbpl")
    r = sub.choices["run"]
    r.add_argument("--fake", action="store_true", help="retriever giả từ corpus; số đo vô nghĩa")
    r.add_argument("--out", default=DEFAULT_OUT, help="thư mục ghi results/<run_id>/report.json")
    r.add_argument(
        "--index-sig", default=None, help="index_sig của index đang đo (hoặc $DOCS_INDEX_SIG)"
    )
    return p


def _validate(suite: Path, raw: Path) -> tuple[list, list[str]]:
    questions = load_questions(suite)
    return questions, validate_questions(questions, raw)


async def _run(args: argparse.Namespace) -> int:
    from mcp_docs.settings import Settings

    from . import backends, runner
    from .fakes import eval_principal

    suite_path = resolve_suite(args.suite)
    raw = raw_dir(args.raw_dir)
    questions, errors = _validate(suite_path, raw)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    settings = Settings()
    factory = backends.fake_factory(raw) if args.fake else backends.real_factory(settings)
    results = await runner.run_all(factory, questions, eval_principal())

    embed_model = None if args.fake else await backends.resolve_embed_model(settings)
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%S")
    report = runner.build_report(
        results,
        run_id=run_id,
        started_at=now.isoformat(),
        suite=suite_path.stem,
        dataset={
            "file": suite_path.name,
            "sha256": sha256_file(suite_path),
            "n": len(questions),
            "distribution": distribution(questions),
        },
        versions=backends.index_versions(
            settings, fake=args.fake, index_sig=args.index_sig, embed_model=embed_model
        ),
        fake=args.fake,
    )
    out_dir = Path(args.out) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(runner.format_table(results))
    if args.fake:
        print("\n[fake] retriever giả: số đo chỉ để kiểm mạch, không có giá trị đánh giá.")
    print(f"\nBáo cáo: {out_dir / 'report.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # console Windows mặc định cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "validate":
            questions, errors = _validate(resolve_suite(args.suite), raw_dir(args.raw_dir))
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"OK: {len(questions)} câu, nhãn đều có trong corpus")
            print(json.dumps(distribution(questions), ensure_ascii=False, indent=2))
            return 0
        return asyncio.run(_run(args))
    except DatasetError as e:
        print(f"lỗi dữ liệu: {e}", file=sys.stderr)
        return 2
    except UnsupportedConfig as e:
        print(f"lỗi cấu hình: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
