"""Port `TextSegmenter`: chuỗi văn bản -> chuỗi term cho full-text (tách từ tiếng Việt)."""

from __future__ import annotations

import abc


class TextSegmenter(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Tên ổn định, đi vào chữ ký chỉ mục (đổi bộ tách từ => nạp lại)."""

    @abc.abstractmethod
    def segment(self, text: str) -> str:
        """Trả chuỗi term phân tách bằng khoảng trắng; tất định, cùng đầu vào cùng đầu ra."""
