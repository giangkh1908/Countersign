"""Decorator `RetryingMessageChannel`: thử lại CHỈ khi chắc chắn tin chưa đi (cùng port `MessageChannel`).

Chỉ thử lại lỗi `safe_to_retry` (kết nối thất bại trước khi request đi, hoặc 429 có `retry_after` ngắn).
Timeout sau khi gửi, 5xx, lỗi giao thức: không thử lại, để lỗi nổi lên và được ghi `unknown`
(gửi đúp vào nhóm công ty tệ hơn là báo "không chắc"). Plumbing HTTP của `RetryingHttpClient` không dùng
ở đây vì nó thử lại cả timeout.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from .ports import ChannelSendError, DeliveryReceipt, MessageChannel


class RetryingMessageChannel(MessageChannel):
    def __init__(
        self,
        inner: MessageChannel,
        *,
        max_attempts: int = 3,
        max_wait_s: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._inner = inner
        self._max_attempts = max_attempts
        self._max_wait = max_wait_s
        self._sleep = sleep
        self._rng = rng

    async def send(self, chat_ref: str, text: str) -> DeliveryReceipt:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._inner.send(chat_ref, text)
            except ChannelSendError as e:
                if not e.safe_to_retry or attempt == self._max_attempts:
                    raise
                if e.retry_after_s is not None:
                    if e.retry_after_s > self._max_wait:
                        raise  # phải chờ quá lâu: để người dùng quyết định, không treo lời gọi
                    wait = e.retry_after_s
                else:
                    wait = self._rng() * min(self._max_wait, 0.2 * 2 ** (attempt - 1))
                await self._sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover
