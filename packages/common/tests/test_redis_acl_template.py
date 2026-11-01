"""ACL redis-state: user `tickets` phải chạy được MULTI/EXEC (kho intent dùng pipeline transaction)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


# ── entrypoint.sh: chạy thật bằng sh trên bản sao trong tmp_path ──────────────────────────
ENTRYPOINT = ACL.parent / "entrypoint.sh"
COMPOSE = ACL.parents[2] / "docker-compose.yml"
_need_tools = pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("sha256sum") is None,
    reason="cần sh và sha256sum",
)


def _placeholders() -> set[str]:
    return set(re.findall(r"@@([A-Z_]+)@@", ACL.read_text(encoding="utf-8")))


def _secrets_used() -> set[str]:
    return set(re.findall(r"\$\(h (\w+)\)", ENTRYPOINT.read_text(encoding="utf-8")))


@_need_tools
def test_entrypoint_renders_acl_with_hashed_passwords(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name in _secrets_used():
        (secrets / name).write_text(f"pw-{name}", encoding="utf-8")
    tmpl = tmp_path / "users.acl.tmpl"
    tmpl.write_bytes(ACL.read_bytes())
    out = tmp_path / "users.acl"
    script = (
        ENTRYPOINT.read_text(encoding="utf-8")
        .replace("/etc/redis/users.acl.tmpl", tmpl.as_posix())
        .replace("/tmp/users.acl", out.as_posix())
        .replace("/run/secrets", secrets.as_posix())
    )
    path = tmp_path / "entrypoint.sh"
    path.write_bytes(script.encode("utf-8"))
    r = subprocess.run(["sh", str(path), "true"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]  # bỏ dòng chú thích
    assert not any("@@" in ln for ln in code)
    on_lines = [ln for ln in code if re.match(r"user \S+ on ", ln)]
    assert on_lines
    for ln in on_lines:
        assert re.search(r"(?:^| )#[0-9a-f]{64}(?: |$)", ln), ln


def test_entrypoint_secrets_declared_and_placeholders_substituted() -> None:
    script = ENTRYPOINT.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"^  redis-state:\n(.*?)(?=^  \S)", compose, re.S | re.M)
    assert block, "không thấy service redis-state"
    declared = re.search(r"secrets:\s*\[([^\]]*)\]", block.group(1))
    assert declared
    names = {x.strip() for x in declared.group(1).split(",")}
    assert _secrets_used() <= names
    for ph in _placeholders():
        assert f"s/@@{ph}@@/" in script, f"thiếu -e cho @@{ph}@@"
