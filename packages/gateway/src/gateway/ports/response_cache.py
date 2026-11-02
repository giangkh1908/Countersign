"""Port `ResponseCache`: kho câu trả lời LLM đã sinh, tra theo khoá do `services/cache_key.py` dựng.

Giá trị là nội dung mật theo đúng phạm vi người hỏi (đã nằm trong khoá). Port không biết khoá có
nghĩa gì; lỗi hạ tầng được caller coi là miss (cache không được làm hỏng đường chính).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """Câu trả lời `finish_reason=stop`, thuần văn bản (không tool call)."""

    content: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    provider: str
    model: str


class ResponseCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> CachedResponse | None: ...

    @abstractmethod
    async def put(self, key: str, value: CachedResponse, ttl_s: int) -> None: ...

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn, mặc định không làm gì
        """Giải phóng kết nối."""
