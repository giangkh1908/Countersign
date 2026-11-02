"""Sinh `users.json` TẠM cho harness RQ4: token user thật aud=llm-gateway, nhãn phạm vi từ claim.

Cách đổi token giống agent (`run_service.py`): đăng nhập bằng client dev-only `e2e-test`
(aud=chat-ui) -> đổi sang aud=agent-service (client chat-ui) -> đổi sang aud=llm-gateway,
scope llm:invoke (client agent-service). Client `e2e-test` được tạo rồi XOÁ trong `finally`.
Tác dụng phụ (dev): đặt lại mật khẩu các user được chọn. Không in token; file chứa token
phải nằm ngoài git (eval/results/ đã gitignore) và bị xoá sau khi dùng.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_USERS = (
    "an.nguyen",
    "an.nguyen#2",
    "binh.tran",
    "lan.dang",
    "minh.huynh",
    "nam.truong",
    "son.mai",
)


def _e2e() -> Any:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
    import close_ticket  # noqa: PLC0415 - helper dev-only, không phải code nghiệp vụ

    return close_ticket


def _as_list(v: object) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def scope_label(claims: dict[str, Any]) -> str:
    """Nhãn phạm vi `dept|clearance|roles` từ claim đã đổi (cùng nhãn = cùng khoá cache)."""
    dept = ",".join(sorted(set(_as_list(claims.get("dept")))))
    clr = ",".join(_as_list(claims.get("clearance")))
    roles = ",".join(sorted(set(_as_list(claims.get("roles") or claims.get("realm_roles")))))
    return f"{dept}|{clr}|{roles}"


def build_users(names: list[str]) -> dict[str, dict[str, str]]:
    ct = _e2e()
    host = urlparse(ct.KC).hostname or ""
    if host not in ct.DEV_KC_HOSTS and os.environ.get("E2E_ALLOW") != "1":
        raise SystemExit(f"Từ chối chạy: Keycloak host {host!r} không phải dev")
    kc = ct.Keycloak()
    out: dict[str, dict[str, str]] = {}
    try:
        # `ten#2` = phiên thứ hai của cùng user (token cấp riêng, cùng phạm vi): giả lập hai người cùng quyền
        kc.ensure_test_setup(sorted({n.split("#")[0] for n in names}))
        for n in names:
            login = kc.login(n.split("#")[0])
            agent_tok = kc.token_for(login, "agent-service", "agent:invoke")
            gw_tok = kc.token_for(agent_tok, "llm-gateway", "llm:invoke", client="agent-service")
            out[n] = {"token": gw_tok, "scope": scope_label(ct.jwt_claims(gw_tok))}
    finally:
        with contextlib.suppress(Exception):
            kc.delete_client()
    return out


def write_users(path: Path, names: list[str]) -> dict[str, str]:
    """Ghi users.json; trả {tên: nhãn phạm vi} để in (không có token)."""
    users = build_users(names)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return {n: v["scope"] for n, v in users.items()}
