"""CLI: uv run python -m data.generator [--seed N] [--out DIR] [--realm FILE] [--sub-map FILE]."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import DEFAULT_OUT, SEED, build
from .users import DEFAULT_REALM


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m data.generator", description=__doc__)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--realm", type=Path, default=DEFAULT_REALM)
    ap.add_argument(
        "--sub-map",
        type=Path,
        default=None,
        help="JSON {username: keycloak_sub}; mặc định sub = username",
    )
    args = ap.parse_args()
    sub_map = json.loads(args.sub_map.read_text(encoding="utf-8")) if args.sub_map else None
    manifest = build(args.out, seed=args.seed, realm_path=args.realm, sub_map=sub_map)
    print(f"OK -> {args.out}  seed={manifest['seed']}  counts={manifest['counts']}")


if __name__ == "__main__":
    main()
