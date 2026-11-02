"""Chạy: `uv run python -m eval.cache run ...` rồi `uv run python -m eval.cache report a.json b.json`.

run    gọi gateway đang chạy (cache tắt hoặc bật tuỳ cấu hình gateway), lưu JSON theo `--label`.
report in bảng so sánh các file JSON (vd cache-off và cache-on); thoát 1 nếu có trúng chéo phạm vi.

`--users-file` là JSON `{"<tên>": {"token": "<user token aud=llm-gateway>", "scope": "<nhãn phạm vi>"}}`
(token ngắn hạn, không commit). Khoá API đọc từ `--key-file`. Không in token hay khoá.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .harness import (
    HttpGatewaySender,
    User,
    format_table,
    leaks,
    load_report,
    run_all,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.cache", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--gateway", default="http://localhost:8000")
    r.add_argument("--key-file", required=True)
    r.add_argument("--users-file", required=True)
    r.add_argument("--model", default="acme-fast")
    r.add_argument("--label", required=True, help="vd cache-off, cache-on")
    r.add_argument("--n", type=int, default=60, help="số request mỗi mức lặp")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--out", help="ghi JSON ra file này")
    p = sub.add_parser("report")
    p.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "report":
        reports = [load_report(Path(f)) for f in args.files]
        print(format_table(reports))
        bad = leaks(reports)
        print(f"\nRÒ RỈ CHÉO PHẠM VI: {bad} " + ("(ĐỎ)" if bad else "(0, xanh)"))
        return 1 if bad else 0

    spec = json.loads(Path(args.users_file).read_text(encoding="utf-8"))
    users = [User(name, v["scope"]) for name, v in spec.items()]
    if len({u.scope for u in users}) < 2:
        print("cần ít nhất 2 phạm vi khác nhau để đo rò rỉ chéo", file=sys.stderr)
        return 2
    sender = HttpGatewaySender(
        args.gateway,
        Path(args.key_file).read_text(encoding="utf-8").strip(),
        {name: v["token"] for name, v in spec.items()},
        args.model,
    )

    async def go():
        try:
            return await run_all(sender, users, label=args.label, n=args.n, seed=args.seed)
        finally:
            await sender.aclose()

    rep = asyncio.run(go())
    print(format_table([rep]))
    if args.out:
        Path(args.out).write_text(rep.to_json(), encoding="utf-8")
    return 1 if leaks([rep]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
