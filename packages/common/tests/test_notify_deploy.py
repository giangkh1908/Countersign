"""Bố trí triển khai notify-mcp: ACL Redis, mạng egress, bot token, khoá intent riêng."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
ACL = (ROOT / "infra/redis/users-state.acl.tmpl").read_text(encoding="utf-8")


def _acl(user: str) -> list[str]:
    for line in ACL.splitlines():
        parts = line.split()
        if len(parts) > 2 and parts[:2] == ["user", user]:
            return parts[2:]
    raise AssertionError(user)


def test_notify_redis_user_scoped_and_reads_taint() -> None:
    rules = _acl("notify")
    assert "~mcp:notify:*" in rules and "~mcp:taint:*" in rules  # đọc taint để chặn trước khi gửi
    assert not any(r.startswith("~mcp:tickets") or r in ("~*", "allkeys") for r in rules)
    assert {"+multi", "+exec", "+discard"} <= set(rules) and "-@dangerous" in rules
    # user khác không đọc được kho intent của notify
    for other in ("tickets", "docs", "bff"):
        assert "~mcp:notify:*" not in _acl(other)


def test_only_gateway_and_notify_on_egress() -> None:
    on_egress = {n for n, s in SERVICES.items() if "egress" in (s.get("networks") or [])}
    assert on_egress == {"gateway", "notify-mcp"}


def test_notify_profile_and_signer_shared() -> None:
    assert SERVICES["notify-mcp"]["profiles"] == ["notify"]
    assert set(SERVICES["approval-signer"]["profiles"]) >= {"tickets", "notify"}
    assert "notify-mcp" in SERVICES["approval-signer"]["environment"]["INTENT_ISSUER_NAMES"]


def test_bot_token_only_mounted_in_notify() -> None:
    holders = [n for n, s in SERVICES.items() if "telegram_bot_token" in (s.get("secrets") or [])]
    assert holders == ["notify-mcp"]
    for n, s in SERVICES.items():  # không ai nhận token qua biến môi trường thường
        env = s.get("environment") or {}
        assert not any("TELEGRAM" in str(k) and not str(k).endswith("_FILE") for k in env), n


def test_intent_private_keys_not_shared() -> None:
    holders = {
        n: [k for k in (s.get("secrets") or []) if "intent_private_key" in k]
        for n, s in SERVICES.items()
    }
    assert holders["tickets-mcp"] == ["intent_private_key"]
    assert holders["notify-mcp"] == ["notify_intent_private_key"]
    assert not any(v for n, v in holders.items() if n not in ("tickets-mcp", "notify-mcp"))


def test_notify_uses_own_key_dir_and_db() -> None:
    env = SERVICES["notify-mcp"]["environment"]
    assert env["INTENT_KEY_ID"] == "notify-mcp-1"
    assert env["MCP_DATABASE_URL_FILE"].endswith("notify_database_url")
    gen = (ROOT / "scripts/gen-secrets.sh").read_text(encoding="utf-8")
    assert "intent-keys/notify-mcp/notify-mcp-1.pem" in gen


def test_default_channels_are_valid_and_token_free() -> None:
    from mcp_notify.channels import load_channels

    cfg = load_channels(ROOT / "infra/notify/channels.yaml")
    assert cfg and all(c.max_class <= 1 for c in cfg.values())
    text = (ROOT / "infra/notify/channels.yaml").read_text(encoding="utf-8")
    assert not re.search(r"\d{6,}:[A-Za-z0-9_-]{20,}", text)  # không có token bot
    assert not re.search(r"-100\d+", text)  # không có chat ID thật


@pytest.mark.parametrize("name", ["30-notify.sql"])
def test_notify_sql_present_and_restricts_updates(name: str) -> None:
    sql = (ROOT / "infra/postgres/init/sql" / name).read_text(encoding="utf-8")
    assert "intent_id uuid UNIQUE" in sql
    assert "GRANT UPDATE (status, detail, updated_at)" in sql
    assert "DELETE" not in sql.split("GRANT")[-1]
