"""Quét canary trong redis-cache (cache-observability.md §4): chỉ đọc, bằng user ACL `ops`.

Mỗi khoá `cache:v1:{ver}:{dept}:{clearance}:{roles}:{model}:{sha}` mang phạm vi của người hỏi. Giá trị
(câu trả lời đã cache) KHÔNG được chứa doc_id, tiêu đề hay vân tay của tài liệu mà phạm vi đó không được xem.
Tài liệu "trái quyền" tính độc lập với RLS, bằng đúng hàm của `eval/e2e/leak_check.py`.

Chạy: `python -m eval.cache scan` (cần stack có profile cache; mật khẩu `ops` đọc trong container từ
secret, không in ra). Thoát 1 nếu có dấu vết trái quyền.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KEY_PREFIX = "cache:v1:"
_EMPTY = "~"

_REDIS_CLI = 'REDISCLI_AUTH="$(cat /run/secrets/redis_ops_password)" redis-cli --user ops'


@dataclass(frozen=True, slots=True)
class KeyScope:
    dept: frozenset[str]
    clearance: int
    roles: frozenset[str]


def parse_key(key: str) -> KeyScope | None:
    """Tách phạm vi khỏi khoá; None nếu khoá sai dạng."""
    parts = key.split(":")
    if len(parts) != 8 or f"{parts[0]}:{parts[1]}:" != KEY_PREFIX:
        return None
    _, _, _ver, dept, clr, roles, _model, _sha = parts

    def many(s: str) -> frozenset[str]:
        return frozenset() if s == _EMPTY else frozenset(s.split(","))

    try:
        clearance = -1 if clr == _EMPTY else int(clr)
    except ValueError:
        return None
    return KeyScope(many(dept), clearance, many(roles))


def cached_text(raw: str) -> str:
    """Giá trị cache -> chuỗi để quét: nội dung đã giải mã JSON cộng bản thô."""
    try:
        d = json.loads(raw)
        return str(d.get("content", "")) + "\n" + raw
    except (ValueError, AttributeError):
        return raw


@dataclass
class ScanResult:
    keys: int = 0
    malformed: int = 0
    with_allowed_trace: int = 0  # đối chứng dương: khoá có dấu vết tài liệu ĐƯỢC phép
    hard: list[tuple[str, str]] = field(default_factory=list)  # (khoá rút gọn, doc_id)
    title: list[tuple[str, str]] = field(default_factory=list)

    @property
    def leaks(self) -> int:
        return len(self.hard) + len(self.title)


def scan_entries(entries: dict[str, str], docs: list[Any], leak_mod: Any) -> ScanResult:
    """`entries` {khoá: giá trị}; `docs` là list[Doc] của leak_check; `leak_mod` là module đó."""
    res = ScanResult()
    for key, raw in entries.items():
        res.keys += 1
        scope = parse_key(key)
        if scope is None:
            res.malformed += 1
            continue
        u = leak_mod.UserCase(key, set(scope.dept), scope.clearance, set(scope.roles))
        forbidden = [d for d in docs if not leak_mod.visible(u, d)]
        allowed = [d for d in docs if leak_mod.visible(u, d)]
        text = cached_text(raw)
        found = leak_mod.scan_blob(text, forbidden)
        short = key.rsplit(":", 1)[0] + ":…"  # bỏ phần băm cho gọn
        res.hard += [(short, d) for d in sorted(found["hard"])]
        res.title += [(short, d) for d in sorted(found["title"])]
        if any(leak_mod.scan_blob(text, allowed)[k] for k in ("hard", "title")):
            res.with_allowed_trace += 1
    return res


def _exec(script: str, stdin: str | None = None) -> str:
    root = Path(__file__).resolve().parents[2]
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "redis-cache", "sh", "-c", script],
        cwd=root,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if p.returncode != 0:
        raise RuntimeError(f"redis-cli lỗi (mã {p.returncode}): {p.stderr.strip()[:200]}")
    return p.stdout


def fetch_entries() -> dict[str, str]:
    """Liệt kê khoá bằng SCAN rồi GET theo lô qua stdin (redis-cli không-tty in nguyên văn, một dòng/giá trị)."""
    keys = [k for k in _exec(f"{_REDIS_CLI} --scan --pattern 'cache:v1:*'").splitlines() if k]
    if not keys:
        return {}
    out = _exec(f"{_REDIS_CLI}", stdin="".join(f"GET {k}\n" for k in keys)).split("\n")
    return {k: (out[i] if i < len(out) else "") for i, k in enumerate(keys)}


def run_scan() -> ScanResult:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
    import leak_check  # noqa: PLC0415 - helper dev-only

    return scan_entries(fetch_entries(), leak_check.load_docs(), leak_check)
