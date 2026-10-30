"""Kiểu dữ liệu và lỗi trung lập ở biên các port của gateway (contracts §9.1 mục 3; 01 §1.2).

Không mang tên vendor. Message của `ProviderError` không chứa URL, header, key hay nội dung người dùng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0  # tổng (gồm cached + cache write)
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    estimated: bool = False  # ước lượng khi client ngắt giữa chừng

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class ChatRequest:
    """Form OpenAI đã chuẩn hoá. `model` là id model của provider (đã resolve từ alias)."""

    alias: str
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=dict)  # temperature, top_p, max_tokens, stop...
    stream: bool = False


@dataclass(slots=True)
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""  # mảnh JSON


@dataclass(slots=True)
class ChatChunk:
    text: str | None = None
    tool_call: ToolCallDelta | None = None
    finish_reason: str | None = None  # stop|length|tool_calls|content_filter
    usage: Usage | None = None


@dataclass(slots=True)
class ChatResponse:
    message: dict[str, Any]  # {"role":"assistant","content":str|None,"tool_calls":[...]}
    finish_reason: str
    usage: Usage
    model: str
    provider: str


class ProviderError(Exception):
    """kind: timeout | connection | http_<status> | protocol | blocked."""

    def __init__(
        self, kind: str, *, retryable: bool = False, retry_after_s: float | None = None
    ) -> None:
        super().__init__(f"provider_error: {kind}")
        self.kind = kind
        self.retryable = retryable
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class KeyRecord:
    """Một API key đã tra (không chứa plaintext). `secret_hmac` = HMAC-SHA256(pepper, secret)."""

    key_id: str
    prefix: str
    secret_hmac: bytes
    name: str
    dept: str
    allowed_models: tuple[str, ...]
    rpm: int
    tpm: int
    max_concurrency: int
    budget_micro: int | None
    trust_end_user_token: bool
    expose_debug: bool
    status: str  # active | revoked | expired
    expires_at: datetime | None
    pii_policy: str = "mask"
    dept_budget_micro: int | None = None


@dataclass(frozen=True, slots=True)
class NewKey:
    """Đầu vào `KeyStore.create`. Plaintext không đi qua port: chỉ có prefix và HMAC."""

    prefix: str
    secret_hmac: bytes
    name: str
    owner_type: str  # service | department | user
    owner_ref: str
    dept: str
    allowed_models: tuple[str, ...]
    rpm: int
    tpm: int
    max_concurrency: int = 8
    budget_micro: int | None = None
    trust_end_user_token: bool = False
    expose_debug: bool = False
    expires_at: datetime | None = None
