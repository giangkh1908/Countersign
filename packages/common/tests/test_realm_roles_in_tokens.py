"""Claim `roles` chỉ có trong token nếu role nằm trong scope mapping (clients có fullScopeAllowed=false).

Thiếu mapping này thì tickets-mcp thấy `roles=[]` => user không xem được ticket phòng mình (RLS/policy
`employee`), docs-mcp lọc sai `allowed_roles`.
"""

import json
from pathlib import Path

REALM = Path(__file__).resolve().parents[3] / "infra/keycloak/realm-acme.json"


def test_acme_claims_scope_maps_every_realm_role() -> None:
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    realm_roles = {r["name"] for r in realm["roles"]["realm"]}
    mapped = {
        role
        for m in realm.get("scopeMappings", [])
        if m.get("clientScope") == "acme-claims"
        for role in m["roles"]
    }
    assert realm_roles <= mapped


def test_users_only_use_declared_roles() -> None:
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    declared = {r["name"] for r in realm["roles"]["realm"]}
    for u in realm["users"]:
        assert set(u.get("realmRoles", [])) <= declared, u["username"]
