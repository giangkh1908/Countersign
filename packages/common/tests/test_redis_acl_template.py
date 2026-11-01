"""ACL redis-state: user `tickets` phải chạy được MULTI/EXEC (kho intent dùng pipeline transaction)."""

from pathlib import Path

ACL = Path(__file__).resolve().parents[3] / "infra/redis/users-state.acl.tmpl"


def _rules(user: str) -> set[str]:
    for line in ACL.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) > 2 and parts[0] == "user" and parts[1] == user:
            return set(parts[2:])
    raise AssertionError(f"user {user} not in ACL template")


def test_tickets_user_can_run_transactions() -> None:
    assert {"+multi", "+exec", "+discard"} <= _rules("tickets")


def test_bff_user_stays_without_transactions() -> None:
    assert not {"+multi", "+exec", "+@transaction", "+@all"} & _rules("bff")


def test_default_user_has_no_nopass_flag() -> None:
    # protected-mode yes + default user `nopass` => Redis từ chối MỌI client ngoài loopback,
    # kể cả đã AUTH. `resetpass` (không có mật khẩu nào) giữ default không đăng nhập được.
    for line in ACL.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts[:2] == ["user", "default"]:
            assert "off" in parts and "resetpass" in parts and "nopass" not in parts
            break
    else:
        raise AssertionError("user default not in ACL template")
