"""CLI admin của gateway: tạo/thu hồi API key (seed không tạo key).

    python -m gateway.cli create-key --name agent --dept IT --owner-type service --owner-ref agent-service \\
        --allowed-models acme-fast,acme-smart --rpm 120 --tpm 200000 --trust-end-user-token
    python -m gateway.cli revoke-key --key-id <uuid> --reason "leaked"
    echo "$KEY" | python -m gateway.cli check-key   # key đọc từ stdin; exit 0 = dùng được, 3 = không có/đã thu hồi
    echo "$KEY" | python -m gateway.cli update-key-models --allowed-models acme-embed,acme-rerank   # đặt lại model, không rotate

Cần `GW_DATABASE_URL`(_FILE) và `GW_KEY_PEPPER`(_FILE). Plaintext chỉ in ra stdout đúng một lần.
Mỗi thao tác ghi một sự kiện `audit` qua `EventSink.append(sync=True)` (không chứa secret).
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import sys
from datetime import datetime
from typing import Any

from acme_common.factory import build_clock, build_event_sink
from acme_common.ports import Clock, EventSink

from .factory import build_key_store
from .ports.errors import KeyAlreadyExists, KeyNotFound
from .ports.key_store import KeyStore
from .services.key_admin import hmac_secret, issue_key, parse_key
from .settings import Settings


def _audit(
    sink: EventSink, clock: Clock, actor: str, action: str, resource: str, details: dict[str, Any]
) -> None:
    sink.append(
        {
            "event": "audit_log",
            "ts": clock.now(),
            "actor_type": "admin",
            "actor_id": actor,
            "action": action,
            "resource": resource,
            "decision": "allow",
            "details": details,
        },
        sync=True,
    )


async def create_key(
    args: argparse.Namespace, keys: KeyStore, sink: EventSink, clock: Clock, settings: Settings
) -> int:
    issued = issue_key(
        settings.key_pepper,
        name=args.name,
        owner_type=args.owner_type,
        owner_ref=args.owner_ref or args.name,
        dept=args.dept,
        allowed_models=tuple(m.strip() for m in args.allowed_models.split(",") if m.strip()),
        rpm=args.rpm,
        tpm=args.tpm,
        max_concurrency=args.max_concurrency,
        trust_end_user_token=args.trust_end_user_token,
        expose_debug=args.expose_debug,
        expires_at=datetime.fromisoformat(args.expires_at) if args.expires_at else None,
    )
    try:
        rec = await keys.create(issued.new, args.actor)
    except KeyAlreadyExists:
        print("error: prefix collision, run again", file=sys.stderr)
        return 1
    _audit(sink, clock, args.actor, "key.create", rec.key_id, {"name": rec.name, "dept": rec.dept})
    await sink.flush(5.0)
    print(f"key_id: {rec.key_id}", file=sys.stderr)
    print(issued.plaintext)  # chỉ hiện lần này
    return 0


async def revoke_key(
    args: argparse.Namespace, keys: KeyStore, sink: EventSink, clock: Clock, settings: Settings
) -> int:
    try:
        await keys.revoke(args.key_id, args.actor, args.reason)
    except KeyNotFound:
        print("error: key not found or already revoked", file=sys.stderr)
        return 1
    _audit(sink, clock, args.actor, "key.revoke", args.key_id, {"reason": args.reason})
    await sink.flush(5.0)
    print(f"revoked {args.key_id}", file=sys.stderr)
    return 0


EXIT_KEY_MISSING = 3  # key không có trong DB hoặc đã thu hồi (khác 1/2 = lỗi hạ tầng)


async def check_key(
    args: argparse.Namespace, keys: KeyStore, sink: EventSink, clock: Clock, settings: Settings
) -> int:
    """Đọc key từ stdin (không argv/env), không in key. 0 = tồn tại và active; 3 = không; 2 = lỗi hạ tầng."""
    parsed = parse_key(sys.stdin.read().strip())
    if parsed is None:
        return EXIT_KEY_MISSING
    prefix, secret = parsed
    try:
        rec = await keys.lookup(prefix)
    except Exception:  # noqa: BLE001 - mọi lỗi hạ tầng (DB...) gộp thành exit 2, không lộ chi tiết
        print("error: không tra được key store", file=sys.stderr)
        return 2
    if rec is None or rec.status != "active":
        return EXIT_KEY_MISSING
    if not hmac.compare_digest(rec.secret_hmac, hmac_secret(secret, settings.key_pepper)):
        return EXIT_KEY_MISSING
    return 0


async def update_key_models(
    args: argparse.Namespace, keys: KeyStore, sink: EventSink, clock: Clock, settings: Settings
) -> int:
    """Đọc key từ stdin, thay `allowed_models` của key đó (không phải rotate). 0 = xong; 3 = key không hợp lệ."""
    models = tuple(m.strip() for m in args.allowed_models.split(",") if m.strip())
    if not models:
        print("error: --allowed-models rỗng", file=sys.stderr)
        return 2
    parsed = parse_key(sys.stdin.read().strip())
    if parsed is None:
        return EXIT_KEY_MISSING
    prefix, secret = parsed
    try:
        rec = await keys.lookup(prefix)
    except Exception:  # noqa: BLE001 - mọi lỗi hạ tầng gộp thành exit 2, không lộ chi tiết
        print("error: không tra được key store", file=sys.stderr)
        return 2
    if rec is None or rec.status != "active":
        return EXIT_KEY_MISSING
    if not hmac.compare_digest(rec.secret_hmac, hmac_secret(secret, settings.key_pepper)):
        return EXIT_KEY_MISSING
    try:
        await keys.update_allowed_models(rec.key_id, models, args.actor)
    except KeyNotFound:
        return EXIT_KEY_MISSING
    _audit(
        sink,
        clock,
        args.actor,
        "key.update_models",
        rec.key_id,
        {"before": list(rec.allowed_models), "after": list(models)},
    )
    await sink.flush(5.0)
    print(f"updated {rec.key_id}", file=sys.stderr)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gateway.cli")
    p.add_argument("--actor", default="cli", help="ghi vào created_by/audit")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-key")
    c.add_argument("--name", required=True)
    c.add_argument("--dept", required=True, help="mã phòng ban (departments.code)")
    c.add_argument("--owner-type", choices=["service", "department", "user"], default="service")
    c.add_argument("--owner-ref", default=None)
    c.add_argument("--allowed-models", required=True, help="vd acme-fast,acme-smart")
    c.add_argument("--rpm", type=int, default=60)
    c.add_argument("--tpm", type=int, default=100_000)
    c.add_argument("--max-concurrency", type=int, default=8)
    c.add_argument("--trust-end-user-token", action="store_true")
    c.add_argument("--expose-debug", action="store_true")
    c.add_argument("--expires-at", default=None, help="ISO 8601, vd 2027-01-01T00:00:00+00:00")
    r = sub.add_parser("revoke-key")
    r.add_argument("--key-id", required=True)
    r.add_argument("--reason", required=True)
    sub.add_parser("check-key", help="kiểm key (đọc stdin) còn dùng được trong DB")
    u = sub.add_parser(
        "update-key-models", help="đặt lại danh sách model của key (đọc stdin), không rotate"
    )
    u.add_argument("--allowed-models", required=True, help="vd acme-embed,acme-rerank")
    return p


async def run(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = parser().parse_args(argv)
    settings = settings or Settings()
    clock = build_clock(settings.clock_adapter, settings)
    keys = build_key_store(settings.gw_keystore_adapter, settings, clock=clock)
    sink = build_event_sink(settings.event_sink_adapter, settings)
    try:
        handler = {
            "create-key": create_key,
            "revoke-key": revoke_key,
            "check-key": check_key,
            "update-key-models": update_key_models,
        }[args.cmd]
        return await handler(args, keys, sink, clock, settings)
    finally:
        await keys.aclose()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
