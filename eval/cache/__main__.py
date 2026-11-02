"""Chạy: `uv run python -m eval.cache run ...` rồi `uv run python -m eval.cache report a.json b.json`.

run    gọi gateway đang chạy (cache tắt hoặc bật tuỳ cấu hình gateway); `--mode plain|agent|both`;
       `--out X` ghi `X.plain.json`, `X.agent.json`.
users  ghi `--out` (users.json tạm, chứa token, xoá sau khi dùng) từ user thật qua Keycloak;
       chỉ in nhãn phạm vi của từng user, không in token.
scan   quét canary (doc_id/tiêu đề/vân tay tài liệu trái quyền) trong redis-cache bằng user ACL ops.
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
    Report,
    User,
    format_table,
    leaks,
    load_report,
    run_all,
)
from .redis_scan import run_scan
from .users import DEFAULT_USERS, write_users


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.cache", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--gateway", default="http://localhost:8000")
    r.add_argument("--key-file", required=True)
    r.add_argument("--users-file", required=True)
    r.add_argument("--model", default="acme-fast")
    r.add_argument("--label", required=True, help="vd cache-off, cache-on")
    r.add_argument("--mode", choices=["plain", "agent", "both"], default="both")
    r.add_argument("--n", type=int, default=60, help="số request mỗi mức lặp")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--out", help="ghi JSON ra file này")
    u = sub.add_parser("users")
    u.add_argument("--out", required=True, help="đường dẫn users.json (đặt ngoài git)")
    u.add_argument("--names", default=",".join(DEFAULT_USERS), help="user Keycloak, phẩy ngăn cách")
    sub.add_parser("scan", help="quét canary trong redis-cache bằng user ops (chỉ đọc)")
    p = sub.add_parser("report")
    p.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "users":
        scopes = write_users(Path(args.out), [x for x in args.names.split(",") if x])
        for name, sc in scopes.items():
            print(f"{name}: {sc}")
        print(
            f"{len(set(scopes.values()))} phạm vi khác nhau; đã ghi {args.out} (xoá sau khi dùng)"
        )
        return 0

    if args.cmd == "scan":
        res = run_scan()
        print(
            f"redis-cache: {res.keys} khoá, {res.malformed} sai dạng, "
            f"{res.with_allowed_trace} khoá có dấu vết tài liệu được phép (đối chứng)"
        )
        for key, doc in res.hard + res.title:
            print(f"  RÒ RỈ: {key} chứa dấu vết {doc}")
        print(f"RÒ RỈ TRONG REDIS: {res.leaks} " + ("(ĐỎ)" if res.leaks else "(0, xanh)"))
        return 1 if res.leaks else 0

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

    modes = ["plain", "agent"] if args.mode == "both" else [args.mode]

    async def go() -> list[Report]:
        try:
            return [
                await run_all(
                    sender, users, label=f"{args.label}-{m}", n=args.n, seed=args.seed, mode=m
                )
                for m in modes
            ]
        finally:
            await sender.aclose()

    reps = asyncio.run(go())
    print(format_table(reps))
    if args.out:  # một file chứa các báo cáo theo chế độ: ghi mỗi chế độ một file <out>.<mode>.json
        for m, rep in zip(modes, reps, strict=True):
            Path(f"{args.out}.{m}.json").write_text(rep.to_json(), encoding="utf-8")
    return 1 if leaks(reps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
