"""Realm export không được chứa client password-grant (backdoor qua mặt đăng nhập trình duyệt).

Client dev-only `e2e-test` do eval/e2e/close_ticket.py tự tạo/xoá qua Admin API (design 04 §4.2).
"""

import json
from pathlib import Path

REALM = Path(__file__).resolve().parents[3] / "infra/keycloak/realm-acme.json"


def _clients() -> list[dict]:
    return json.loads(REALM.read_text(encoding="utf-8"))["clients"]


def test_no_client_enables_direct_access_grants() -> None:
    bad = [c["clientId"] for c in _clients() if c.get("directAccessGrantsEnabled") is True]
    assert bad == []


def test_no_e2e_test_client_in_realm() -> None:
    assert "e2e-test" not in {c["clientId"] for c in _clients()}
