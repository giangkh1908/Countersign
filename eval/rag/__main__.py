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
    load_articles,
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
        ("diagnose", "chẩn đoán RRF và đo trùng từ câu hỏi – Điều đúng"),
    ):
        s = sub.add_parser(name, help=help_)
        s.add_argument(
            "--suite", default="vbpl-v1", help="tên suite (eval/rag/<tên>.jsonl) hoặc đường dẫn"
        )
        s.add_argument("--raw-dir", default=None, help="mặc định $VBPL_RAW_DIR hoặc data/raw/vbpl")
    c = sub.add_parser("compare", help="so sánh cấu hình trong report.json (chênh lệch theo cặp)")
    c.add_argument("report", help="đường dẫn report.json của `run`")
    c.add_argument("--baseline", default="hybrid")
    c.add_argument("--metric", default="recall@5")
    c.add_argument("--select", default="", help="danh sách cấu hình để kiểm tra chọn-trên-nửa-bộ")
    sub.choices["diagnose"].add_argument(
        "--out", default=DEFAULT_OUT, help="thư mục ghi diagnose.json"
    )
    r = sub.choices["run"]
    r.add_argument("--fake", action="store_true", help="retriever giả từ corpus; số đo vô nghĩa")
    r.add_argument("--out", default=DEFAULT_OUT, help="thư mục ghi results/<run_id>/report.json")
    r.add_argument(
        "--configs",
        default="default",
        help="default | sweep | danh sách cấu hình cách nhau dấu phẩy (xem backends.SUFFIXES)",
    )
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
    configs = backends.parse_configs(args.configs)
    factory = backends.fake_factory(raw) if args.fake else backends.real_factory(settings, configs)
    results = await runner.run_all(factory, questions, eval_principal(), configs)

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


async def _diagnose(args: argparse.Namespace) -> int:
    from mcp_docs.settings import Settings

    from . import backends, diagnose
    from .fakes import eval_principal

    raw = raw_dir(args.raw_dir)
    questions, errors = _validate(resolve_suite(args.suite), raw)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    configs = ("vector", "hybrid@nc250")
    factory = backends.real_factory(Settings(), configs)
    vector, hybrid = factory(configs[0]), factory(configs[1])
    try:
        rrf = await diagnose.diagnose_rrf(vector, hybrid, questions, eval_principal())
    finally:
        await vector.aclose()
        await hybrid.aclose()
    doc_nums = sorted({d for q in questions for d, _ in q.gold})
    texts = diagnose.load_article_texts(raw, sorted(load_articles(raw)))
    overlap = diagnose.lexical_overlap(questions, texts)
    out_dir = Path(args.out) / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-diagnose")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"rrf": rrf, "overlap": overlap, "gold_docs": doc_nums}
    (out_dir / "diagnose.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in rrf.items() if k != "cases"}, ensure_ascii=False, indent=2))
    print(
        json.dumps({k: v for k, v in overlap.items() if k != "rows"}, ensure_ascii=False, indent=2)
    )
    print(f"\nChi tiết: {out_dir / 'diagnose.json'}")
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
        # psycopg async không chạy trên ProactorEventLoop (mặc định của Windows)
        if args.cmd == "compare":
            from . import compare

            sel = [x for x in args.select.split(",") if x]
            print(compare.run(args.report, args.baseline, args.metric, sel))
            return 0
        if args.cmd == "diagnose":
            return asyncio.run(_diagnose(args), loop_factory=asyncio.SelectorEventLoop)
        return asyncio.run(_run(args), loop_factory=asyncio.SelectorEventLoop)
    except DatasetError as e:
        print(f"lỗi dữ liệu: {e}", file=sys.stderr)
        return 2
    except UnsupportedConfig as e:
        print(f"lỗi cấu hình: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
