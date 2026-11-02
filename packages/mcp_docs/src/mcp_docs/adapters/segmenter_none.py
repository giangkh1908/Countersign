"""Adapter `TextSegmenter` `none`: trả nguyên văn (tương đương cột `tsv` không tách từ)."""

from __future__ import annotations

from ..ports.text_segmenter import TextSegmenter


class NoSegmenter(TextSegmenter):
    @property
    def name(self) -> str:
        return "none"

    def segment(self, text: str) -> str:
        return text
