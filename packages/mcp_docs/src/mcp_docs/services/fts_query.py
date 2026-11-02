"""Tiền xử lý truy vấn cho nhánh full-text: bỏ từ dừng tiếng Việt (chỉ phía truy vấn).

Danh sách chọn trước theo loại từ (đại từ, liên từ, giới từ, trợ từ, từ để hỏi), KHÔNG chọn theo
bộ câu hỏi đánh giá. Chỉ loại từ đơn âm tiết; không đụng tới thuật ngữ pháp lý.
So khớp trên chữ thường đã NFC, trước khi bỏ dấu (bỏ dấu sẽ làm "là"/"la" lẫn nhau).
Nếu loại hết thì trả lại truy vấn gốc để không biến nhánh FTS thành rỗng.
"""

from __future__ import annotations

import re
import unicodedata

VI_STOPWORDS: frozenset[str] = frozenset(
    {
        # liên từ, giới từ, trợ từ
        "và", "hoặc", "hay", "với", "của", "cho", "để", "trong", "ngoài", "trên", "dưới",
        "theo", "từ", "tại", "bởi", "về", "tới", "đến", "vào", "ra", "lên", "xuống", "như",
        "nếu", "thì", "mà", "nhưng", "nên", "vì", "do", "khi", "lúc", "sau", "trước", "rằng",
        "cũng", "vẫn", "còn", "đã", "đang", "sẽ", "rồi", "vừa", "mới", "chỉ", "cả", "đều",
        # đại từ, chỉ định, lượng từ
        "tôi", "mình", "em", "anh", "chị", "bạn", "họ", "ai", "này", "đó", "kia", "ấy",
        "các", "những", "một", "mọi", "nhiều", "bao", "nhiêu",
        # hệ từ, trợ động từ phổ biến
        "là", "có", "được", "bị", "phải", "cần", "muốn", "thể", "không", "chưa",
        # từ để hỏi
        "gì", "nào", "sao", "đâu", "thế",
    }
)  # fmt: skip

_TOKEN = re.compile(r"\w+", re.UNICODE)


def strip_stopwords(text: str, stopwords: frozenset[str] = VI_STOPWORDS) -> str:
    """Bỏ các từ dừng khỏi truy vấn; giữ thứ tự và từ còn lại. Loại hết thì trả `text` gốc."""
    tokens = _TOKEN.findall(unicodedata.normalize("NFC", text).lower())
    kept = [t for t in tokens if t not in stopwords]
    return " ".join(kept) if kept else text
