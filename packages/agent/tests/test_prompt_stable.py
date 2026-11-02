"""System prompt của agent phải tĩnh: không thời gian, id biến đổi hay nội suy (exact cache ở gateway
dựa vào việc hai câu hỏi giống nhau cho cùng prompt; cache-observability.md §1)."""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import agent.agents as agents_pkg
import pytest

_MODULES = ("docs", "report", "ticket")
_VOLATILE_IMPORTS = {"datetime", "time", "uuid", "random", "secrets"}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}|[0-9a-f]{8}-[0-9a-f]{4}-")


@pytest.mark.parametrize("name", _MODULES)
def test_prompt_is_static_text(name: str) -> None:
    mod = importlib.import_module(f"agent.agents.{name}")
    prompt = mod._PROMPT
    assert isinstance(prompt, str) and prompt
    assert "{" not in prompt and "}" not in prompt  # không dùng format/f-string
    assert not _DATE.search(prompt)


@pytest.mark.parametrize("name", _MODULES)
def test_agent_modules_do_not_import_volatile_sources(name: str) -> None:
    src = Path(agents_pkg.__file__).with_name(f"{name}.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert not imported & _VOLATILE_IMPORTS
