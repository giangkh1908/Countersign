"""Mã ngoài `packages/` (eval/, data/, scripts/) không ai import khi chạy pytest, nên đổi tên module
làm nó chết âm thầm. Quét AST: mọi import tuyệt đối thuộc package workspace phải import được và
tên trong `from x import y` phải tồn tại."""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("eval", "data", "scripts")
WORKSPACE = {
    "acme_common",
    "agent",
    "bff",
    "gateway",
    "mcp_docs",
    "mcp_tickets",
    "mcp_notify",
    "approval_signer",
    "mock_provider",
}


def _imports(path: Path) -> list[tuple[str, str | None]]:
    """(module, name|None) cho mỗi import tuyệt đối thuộc workspace."""
    out: list[tuple[str, str | None]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            out += [(a.name, None) for a in node.names if a.name.split(".")[0] in WORKSPACE]
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] in WORKSPACE
        ):
            out += [(node.module, a.name) for a in node.names if a.name != "*"]
    return out


def _files() -> list[Path]:
    return sorted(p for d in SCAN_DIRS for p in (ROOT / d).rglob("*.py"))


def _check(module: str, name: str | None) -> str | None:
    try:
        mod = importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 - báo nguyên nhân thay vì làm vỡ cả phiên
        return f"không import được `{module}`: {e!r}"
    if name and not hasattr(mod, name) and importlib.util.find_spec(f"{module}.{name}") is None:
        return f"`{module}` không có `{name}`"
    return None


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_workspace_imports_resolve(path: Path) -> None:
    errors = [e for m, n in _imports(path) if (e := _check(m, n))]
    assert not errors, errors


def test_scan_finds_files() -> None:
    assert any(p.name == "close_ticket.py" for p in _files())
