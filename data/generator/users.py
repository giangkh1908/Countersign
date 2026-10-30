"""Người dùng ACME: đọc từ realm Keycloak (không tự bịa user).

Realm không cố định `id` (sub) của user -> Keycloak cấp UUID khi import. Vì vậy `sub` mặc định
là `username`; truyền `sub_map` (username -> sub thật, lấy từ Keycloak sau khi import) để seed
khớp JWT thật.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REALM = REPO_ROOT / "infra" / "keycloak" / "realm-acme.json"


@dataclass(frozen=True)
class User:
    sub: str
    username: str
    employee_id: str
    departments: tuple[str, ...]
    clearance: int
    roles: tuple[str, ...]

    @property
    def department(self) -> str:
        return self.departments[0]


def load_users(
    realm_path: Path = DEFAULT_REALM, sub_map: dict[str, str] | None = None
) -> list[User]:
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    sub_map = sub_map or {}
    users: list[User] = []
    for u in realm["users"]:
        attrs = u["attributes"]
        name = u["username"]
        users.append(
            User(
                sub=sub_map.get(name, name),
                username=name,
                employee_id=attrs["employee_id"][0],
                departments=tuple(attrs["department"]),
                clearance=int(attrs["clearance"][0]),
                roles=tuple(u.get("realmRoles", [])),
            )
        )
    return users


def staff_of(users: list[User], dept: str) -> list[User]:
    """User có role `employee` thuộc phòng `dept` (có thể làm assignee)."""
    return [u for u in users if u.department == dept and "employee" in u.roles]


def manager_of(users: list[User], dept: str) -> User:
    for u in users:
        if u.department == dept and "dept_manager" in u.roles:
            return u
    raise LookupError(f"không có dept_manager cho {dept}")
