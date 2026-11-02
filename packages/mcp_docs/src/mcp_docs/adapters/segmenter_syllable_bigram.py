"""Adapter `TextSegmenter` `syllable_bigram`: giữ âm tiết đơn, thêm mọi cặp âm tiết liền kề.

Tiếng Việt viết tách âm tiết nên "hợp đồng lao động" thành các term rời. Thêm bigram "hợpđồng",
"đồnglao"... để cụm từ khớp như một term. Bigram được NỐI TRỰC TIẾP (không dùng "_"): bộ phân tích
mặc định của Postgres coi "_" là dấu cách và tách lại bigram thành hai term. Cặp chỉ ghép khi hai
âm tiết cách nhau bằng khoảng trắng thuần (dấu câu, xuống dòng chặt đứt cặp). Thuần Python, tất định.
"""

from __future__ import annotations

import re

from ..ports.text_segmenter import TextSegmenter

_SYLLABLE = re.compile(r"\w+", re.UNICODE)


class SyllableBigramSegmenter(TextSegmenter):
    @property
    def name(self) -> str:
        return "syllable_bigram"

    def segment(self, text: str) -> str:
        out: list[str] = []
        prev: re.Match[str] | None = None
        for m in _SYLLABLE.finditer(text):
            word = m.group().lower()
            out.append(word)
            if prev is not None:
                gap = text[prev.end() : m.start()]
                if gap and not gap.strip(" \t"):
                    out.append(prev.group().lower() + word)
            prev = m
        return " ".join(out)
