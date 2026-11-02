"""Realm export không được chứa client password-grant (backdoor qua mặt đăng nhập trình duyệt).

Client dev-only `e2e-test` do eval/e2e/close_ticket.py tự tạo/xoá qua Admin API.
"""

import json
from pathlib import Path

REALM = Path(__file__).resolve().parents[3] / "infra/keycloak/realm-acme.json"


def _clients() -> list[dict]:
    return json.loads(REALM.read_text(encoding="utf-8"))["clients"]


def test_no_client_enables_direct_access_grants() -> None:
    bad = [c["clientId"] for c in _clients() if c.get("directAccessGrantsEnabled") is True]
    assert bad == []


def test_all_clients_have_direct_access_grants_disabled_explicitly_or_default() -> None:
    # Mọi client phải khác true (thiếu khoá = mặc định false của Keycloak khi import).
    assert all(c.get("directAccessGrantsEnabled") is not True for c in _clients())


def test_admin_cli_declared_with_password_grant_disabled() -> None:
    # Keycloak tự tạo admin-cli (password grant bật) nếu realm không khai; phải khai tường minh = false.
    admin_cli = [c for c in _clients() if c["clientId"] == "admin-cli"]
    assert len(admin_cli) == 1
    assert admin_cli[0]["directAccessGrantsEnabled"] is False


def test_no_e2e_test_client_in_realm() -> None:
    assert "e2e-test" not in {c["clientId"] for c in _clients()}
