"""Realm phải cho client `chat-ui` xin đúng scope mà BFF gửi lên Keycloak (bug phát hiện bởi E2E trình duyệt:
`invalid_scope: openid profile` vì realm không có client scope `profile`)."""

import inspect
import json
from pathlib import Path

from bff.services.oidc import OidcClient

REALM = Path(__file__).resolve().parents[4] / "infra/keycloak/realm-acme.json"


def test_chat_ui_can_request_every_scope_bff_sends() -> None:
    default = inspect.signature(OidcClient.__init__).parameters["scope"].default
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    client = next(c for c in realm["clients"] if c["clientId"] == "chat-ui")
    allowed = set(client["defaultClientScopes"]) | set(client["optionalClientScopes"])
    defined = {s["name"] for s in realm["clientScopes"]}
    missing = [s for s in default.split() if s != "openid" and s not in allowed]
    assert missing == []
    assert allowed <= defined


def test_profile_scope_not_listed_in_access_token_scope() -> None:
    """Nếu `profile` nằm trong claim `scope`, token exchange bị từ chối `scope_escalation`."""
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    profile = next(s for s in realm["clientScopes"] if s["name"] == "profile")
    assert profile["attributes"]["include.in.token.scope"] == "false"
