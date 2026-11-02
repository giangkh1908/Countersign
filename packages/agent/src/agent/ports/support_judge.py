"""Port `SupportJudge`: đánh giá một câu có được một đoạn nguồn hỗ trợ hay không (rag-citations §5.3).

Không import vendor. Adapter gọi LLM-judge nằm ở `adapters/`; fake cho test ở `testing.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

Verdict = Literal["supported", "partial", "unsupported", "unverified"]


class SupportVerdict(BaseModel):
    """Kết quả một lần chấm cặp (câu, đoạn).

    `unverified` + `error` khác rỗng: judge không trả được JSON hợp lệ (không bao giờ coi là supported).
    `calls`/`input_tokens`/`output_tokens`: chi phí thực của lần chấm này (kể cả lần thử lại).
    """

    verdict: Verdict
    evidence_quote: str = ""
    reason: str = ""
    error: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class SupportJudge(ABC):
    @abstractmethod
    async def judge(self, sentence: str, passage: str) -> SupportVerdict:
        """Chấm `sentence` theo `passage`. Lỗi truyền tải (gateway) được ném ra; JSON hỏng thì trả `unverified`."""
