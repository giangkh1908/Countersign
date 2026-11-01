"""Port `DocumentLoader`: `load(path) -> Document` (registry theo đuôi file). Adapter v1: `markdown`."""

from __future__ import annotations

import abc
from pathlib import Path

from .types import Document


class DocumentLoader(abc.ABC):
    @abc.abstractmethod
    def load(self, path: Path, *, source_path: str) -> Document:
        """Đọc một file thành `Document` (đã chuẩn hoá NFC). `source_path` là đường dẫn logic để trích dẫn."""
