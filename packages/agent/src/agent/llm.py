"""`make_chat_model(role)`: hàm thường (không phải port) trả chat model trỏ tới gateway theo alias.

Gateway nói giao thức OpenAI-compatible (chuẩn mở, không bọc, contracts §9.1 mục 10). Header:
`Authorization: Bearer <API key agent>` (do ChatOpenAI đặt) + `X-Acme-User-Token: <token aud=llm-gateway>`.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

import httpx
import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .ports.errors import ConfigError, GatewayError
from .settings import DEFAULT_ROLE_ALIASES, Settings


@dataclass
class CostCollector:
    """Gom chi phí/ID request của gateway trong một lượt (header `x-acme-*`)."""

    calls: list[dict] = field(default_factory=list)
    _drained: int = 0

    def add(
        self, request_id: str | None, usd: float | None, alias: str | None, cache: str | None
    ) -> None:
        self.calls.append(
            {"request_id": request_id, "alias": alias, "usd": usd or 0.0, "cache": cache}
        )

    @property
    def total_usd(self) -> float:
        return sum(c["usd"] for c in self.calls)

    def drain(self) -> tuple[float, int]:
        """(USD, số call) phát sinh từ lần drain trước, để node cộng vào state."""
        new = self.calls[self._drained :]
        self._drained = len(self.calls)
        return sum(c["usd"] for c in new), len(new)


current_cost: contextvars.ContextVar[CostCollector | None] = contextvars.ContextVar(
    "agent_current_cost", default=None
)


async def _on_response(resp: httpx.Response) -> None:
    c = current_cost.get()
    if c is None:
        return
    h = resp.headers
    try:
        usd = float(h["x-acme-cost-usd"]) if "x-acme-cost-usd" in h else None
    except ValueError:
        usd = None
    c.add(h.get("x-acme-request-id"), usd, h.get("x-acme-model"), h.get("x-acme-cache"))


def build_llm_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3, read=95, write=10, pool=3),
        event_hooks={"response": [_on_response]},
    )


def make_chat_model(
    role: str,
    *,
    settings: Settings,
    gateway_user_token: str,
    run_id: str,
    http_client: httpx.AsyncClient | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> BaseChatModel:
    alias = settings.agent_role_aliases.get(role) or DEFAULT_ROLE_ALIASES.get(role)
    if alias is None:
        raise ConfigError(f"unknown chat role {role!r}")
    if not settings.agent_gateway_key:
        raise ConfigError("AGENT_GATEWAY_KEY is required")
    return ChatOpenAI(
        base_url=settings.agent_gateway_url,
        api_key=SecretStr(settings.agent_gateway_key),
        model=alias,
        temperature=temperature,
        max_tokens=max_tokens,
        stream_usage=True,
        max_retries=0,
        default_headers={
            "X-Acme-User-Token": gateway_user_token,
            "X-Acme-Client-Request-Id": run_id,
        },
        http_async_client=http_client,
    )


_USER_MESSAGES: dict[str, tuple[str, bool]] = {
    "budget_exceeded": (
        "Ngân sách AI của phòng ban trong tháng đã hết. Vui lòng liên hệ quản trị viên.",
        False,
    ),
    "rate_limited": ("Hệ thống đang bận. Vui lòng thử lại sau ít giây.", True),
    "pii_blocked": ("Tin nhắn chứa thông tin cá nhân nhạy cảm mà chính sách không cho gửi.", False),
    "injection_blocked": ("Yêu cầu bị chặn vì có dấu hiệu cố điều khiển hệ thống.", False),
    "context_too_large": ("Cuộc hội thoại quá dài, hãy bắt đầu cuộc trò chuyện mới.", False),
    "auth": ("Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.", False),
    "provider_unavailable": ("Dịch vụ AI tạm thời không phản hồi. Bạn thử lại sau ít phút.", True),
    "internal": ("Hệ thống đang gặp sự cố cấu hình.", False),
}


def _gw(code: str) -> GatewayError:
    msg, retry = _USER_MESSAGES[code]
    return GatewayError(code, msg, retryable=retry)


def translate_llm_error(exc: BaseException) -> GatewayError | None:
    """Dịch lỗi client OpenAI sang `GatewayError`. Không in message thô của gateway."""
    if isinstance(exc, openai.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        err = body.get("error", body) if isinstance(body, dict) else {}
        code = err.get("code") if isinstance(err, dict) else None
        st = exc.status_code
        if st == 402 or code == "budget_exceeded":
            return _gw("budget_exceeded")
        if st == 429:
            return _gw("rate_limited")
        if code == "pii_blocked":
            return _gw("pii_blocked")
        if code == "prompt_injection_detected":
            return _gw("injection_blocked")
        if st == 413:
            return _gw("context_too_large")
        if code == "invalid_end_user_token":
            return _gw("auth")
        if st in (401, 403):
            return _gw("internal")
        return _gw("provider_unavailable")
    if isinstance(exc, openai.APIConnectionError | openai.APITimeoutError):
        return _gw("provider_unavailable")
    return None
