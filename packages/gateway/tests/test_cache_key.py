"""Khoá exact cache: phạm vi quyền, model, phiên bản index, allowlist ký tự (hàm thuần, không Redis)."""

from __future__ import annotations

from typing import Any

import pytest
from acme_common.ports import Principal
from gateway.services.cache_key import build_cache_key

MSG = [{"role": "user", "content": "Thời hạn nộp hồ sơ là bao lâu?"}]


def user(
    *,
    dept: tuple[str, ...] = ("IT",),
    clearance: int | None = 1,
    roles: tuple[str, ...] = ("staff",),
) -> Principal:
    return Principal(
        sub="u1",
        audience=("llm-gateway",),
        azp="chat-ui",
        scopes=frozenset(),
        expires_at=2e9,
        dept=dept,
        clearance=clearance,
        roles=roles,
    )


def key(u: Principal | None = None, **kw: Any) -> str | None:
    args: dict[str, Any] = {
        "user": u if u is not None else user(),
        "provider": "mock",
        "model": "m1",
        "messages": MSG,
        "params": {"temperature": 0.0, "max_tokens": 64},
        "tools": None,
        "tool_choice": None,
        "index_version": "0",
    }
    args.update(kw)
    return build_cache_key(**args)


def test_same_request_same_key_and_literal_scope() -> None:
    k = key()
    assert k == key()
    assert k is not None and k.startswith("cache:v1:0:IT:1:staff:mock.m1:")


@pytest.mark.parametrize(
    "other",
    [
        user(dept=("HR",)),
        user(clearance=2),
        user(clearance=None),
        user(roles=("manager",)),
        user(roles=("staff", "manager")),
        user(dept=()),
    ],
)
def test_different_scope_never_shares_key(other: Principal) -> None:
    assert key(other) != key()


def test_scope_collision_via_separator_is_refused() -> None:
    # dept chứa ":" hoặc "," không được ghép thành khoá trùng phạm vi khác
    assert key(user(dept=("IT:1",))) is None
    assert key(user(roles=("a:b",))) is None
    assert key(user(dept=("a/b",))) is None
    assert key(user(dept=("x" * 65,))) is None


def test_role_order_does_not_matter() -> None:
    assert key(user(roles=("a", "b"))) == key(user(roles=("b", "a")))


def test_empty_scope_marker_does_not_collide_with_real_value() -> None:
    assert key(user(dept=())) != key(user(dept=("~",)))  # "~" bị allowlist từ chối
    assert key(user(dept=("~",))) is None


def test_model_prompt_params_and_index_version_change_key() -> None:
    base = key()
    assert key(model="m2") != base
    assert key(provider="anthropic") != base
    assert key(messages=[{"role": "user", "content": "khác"}]) != base
    assert key(params={"temperature": 0.7, "max_tokens": 64}) != base
    assert key(index_version="1") != base


def test_not_cacheable() -> None:
    assert (
        build_cache_key(
            user=None,
            provider="mock",
            model="m1",
            messages=MSG,
            params={},
            tools=None,
            tool_choice=None,
            index_version="0",
        )
        is None
    )
    assert key(tools=[{"type": "function", "function": {"name": "x"}}]) is None
    assert key(tool_choice="auto") is None
    assert key(messages=[*MSG, {"role": "tool", "content": "r", "tool_call_id": "1"}]) is None
    assert key(messages=[{"role": "assistant", "content": None, "tool_calls": []}]) is None
    assert key(index_version="a:b") is None


def test_evidence_keyed_mode_drops_scope_only_for_measurement() -> None:
    a, b = user(dept=("IT",)), user(dept=("HR",), roles=("x",))
    assert key(a, strict=False) == key(b, strict=False)
    assert key(a) != key(b)
