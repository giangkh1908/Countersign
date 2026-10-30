"""Adapter `DocumentLoader` cho `.md`: cắt theo heading (bỏ qua `#` trong khối code rào ```)."""

from __future__ import annotations

import re
from pathlib import Path

from ..normalize import normalize_text
from ..ports.document_loader import DocumentLoader
from ..ports.types import Document, Section

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class MarkdownLoader(DocumentLoader):
    def load(self, path: Path, *, source_path: str) -> Document:
        text = normalize_text(path.read_text(encoding="utf-8"))
        stack: list[tuple[int, str]] = []
        sections: list[Section] = []
        buf: list[str] = []
        title: str | None = None
        in_fence = False

        def flush() -> None:
            body = "\n".join(buf).strip()
            buf.clear()
            if body:
                sections.append(Section(tuple(h for _, h in stack), body))

        for line in text.split("\n"):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            m = None if in_fence else _HEADING.match(line)
            if not m:
                buf.append(line)
                continue
            flush()
            level, head = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, head))
            if title is None and level == 1:
                title = head
        flush()
        return Document(source_path, title or Path(source_path).stem, tuple(sections))
