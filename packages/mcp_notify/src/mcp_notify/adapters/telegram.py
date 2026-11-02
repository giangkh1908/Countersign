"""Adapter `telegram` cho port `MessageChannel` (Bot API `sendMessage`).

BOT TOKEN NẰM TRONG URL (`/bot<token>/sendMessage`), nên đây là chỗ dễ rò nhất của A1:
- `acme_common.telemetry` gọi `HTTPXClientInstrumentor().instrument()` TOÀN CỤC (gắn URL vào span).
  Client của adapter tự gỡ instrumentation của chính nó; nếu gỡ không được thì KHÔNG khởi tạo (fail-closed).
- `httpx` log URL ở INFO: gắn bộ lọc lên logger `httpx`/`httpcore` bỏ mọi bản ghi chứa token hoặc host Bot API.
- Lỗi chỉ gồm `kind` và `status` (`ChannelSendError`); exception gốc không được nối chuỗi (raise ngoài
  khối `except`, nên không có `__context__`/`__cause__` mang URL).
- Một lần gọi = một request. Retry (chỉ khi chắc chắn chưa gửi) là việc của decorator `RetryingMessageChannel`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from ..ports import ChannelSendError, DeliveryReceipt, MessageChannel

API_BASE = "https://api.telegram.org"
API_HOST = "api.telegram.org"
_LOGGERS = ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2")
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


class _SecretFilter(logging.Filter):
    """Bỏ bản ghi chứa token hoặc host Bot API (client này log URL ở INFO)."""

    def __init__(self, secrets: set[str]) -> None:
        super().__init__()
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - bản ghi hỏng thì bỏ luôn, không để lọt
            return False
        return not any(s in msg for s in self._secrets)


_filter = _SecretFilter({API_HOST})


def _install_log_filter(token: str) -> None:
    _filter._secrets.add(token)
    for name in _LOGGERS:
        lg = logging.getLogger(name)
        if _filter not in lg.filters:
            lg.addFilter(_filter)


def _detach_instrumentation(client: httpx.AsyncClient) -> None:
    """Gỡ instrumentation OTel khỏi riêng client này; còn bị bọc thì từ chối khởi tạo."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError:
        return  # không có OTel thì không có gì bọc
    HTTPXClientInstrumentor.uninstrument_client(client)
    handler = getattr(client._transport, "handle_async_request", None)
    if hasattr(handler, "__wrapped__"):
        raise RuntimeError("telegram client is still instrumented")


class TelegramMessageChannel(MessageChannel):
    def __init__(
        self,
        bot_token: str,
        chat_resolver: Callable[[str], str | None],
        *,
        api_base: str = API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("telegram bot token is required")
        self._token = bot_token
        self._resolve = chat_resolver
        self._base = api_base.rstrip("/")
        _install_log_filter(bot_token)
        self._client = httpx.AsyncClient(timeout=_TIMEOUT, transport=transport)
        _detach_instrumentation(self._client)

    def __repr__(self) -> str:
        return "TelegramMessageChannel()"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(self, chat_ref: str, text: str) -> DeliveryReceipt:
        chat_id = self._resolve(chat_ref)
        if not chat_id:
            raise ChannelSendError("not_configured", delivered="no")
        url = f"{self._base}/bot{self._token}/sendMessage"
        body = {
            "chat_id": chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},  # văn bản thuần: không parse_mode
        }
        failure: ChannelSendError | None = None
        resp: httpx.Response | None = None
        try:
            resp = await self._client.post(url, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            failure = ChannelSendError("connect", delivered="no")  # request chưa đi
        except httpx.TimeoutException:
            failure = ChannelSendError("timeout")  # có thể đã gửi
        except httpx.TransportError:
            failure = ChannelSendError("transport")
        except Exception:  # noqa: BLE001 - không biết gì thì coi như không chắc, không lộ nội dung lỗi
            failure = ChannelSendError("internal")
        if failure is not None:
            raise failure  # ngoài khối except: không kéo theo exception gốc (có thể chứa URL)
        assert resp is not None
        return _parse(resp)


def _parse(resp: httpx.Response) -> DeliveryReceipt:
    status = resp.status_code
    data: Any = None
    try:
        data = resp.json()
    except ValueError:
        data = None
    ok = isinstance(data, dict) and data.get("ok") is True
    if status == 200 and ok:
        result = data.get("result") if isinstance(data, dict) else None
        mid = result.get("message_id") if isinstance(result, dict) else None
        return DeliveryReceipt(message_ref=str(mid) if isinstance(mid, int) else "")
    code = status
    if isinstance(data, dict) and isinstance(data.get("error_code"), int):
        code = data["error_code"] if status == 200 else status
    if code == 429:
        retry: float | None = None
        params = data.get("parameters") if isinstance(data, dict) else None
        if isinstance(params, dict) and isinstance(params.get("retry_after"), int | float):
            retry = float(params["retry_after"])
        raise ChannelSendError("rate_limited", status=429, delivered="no", retry_after_s=retry)
    if 400 <= code < 500:
        raise ChannelSendError("http_4xx", status=code, delivered="no")
    if code >= 500:
        raise ChannelSendError("http_5xx", status=code)
    raise ChannelSendError("bad_response", status=status)
