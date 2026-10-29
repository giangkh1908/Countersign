"""Healthcheck cho container policy-sidecar (docker-compose: `python -m policy_sidecar.healthcheck`).

Exit 0 khi `/healthz` trả 200, khác 0 nếu không.
`--require-lock-verified`: theo contracts §7.1 chỉ xanh khi đã verify sha256 mọi file trong
`models.lock`. TODO(M4): khi nạp model thật, `/healthz` (hoặc endpoint riêng) báo trạng thái verify
và cờ này phải kiểm trạng thái đó. Hiện là khung nên chỉ kiểm `/healthz`.
"""

import argparse
import sys
import urllib.request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="policy_sidecar.healthcheck")
    parser.add_argument("--url", default="http://127.0.0.1:8010/healthz")
    parser.add_argument("--require-lock-verified", action="store_true")
    args = parser.parse_args(argv)
    try:
        with urllib.request.urlopen(args.url, timeout=2) as resp:
            return 0 if resp.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
