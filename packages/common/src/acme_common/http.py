"""`RetryingHttpClient`: plumbing HTTP dùng chung bằng composition (timeout, phân loại lỗi, backoff có jitter, fail fast 4xx trừ 429). Xem docs/design/contracts.md §9.1 mục 7."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx


class HttpError(Exception):
    """Lỗi truyền tải đã phân loại. `kind` ∈ timeout | connection | http_<status>.

    Message chỉ có `kind`: không URL, header hay body.
    """

    def __init__(self, kind: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(f"http_error: {kind}")
        self.kind = kind
        self.retryable = retryable
        self.status = status


class RetryingHttpClient:
    """Adapter giữ một instance (composition), không kế thừa.

    - timeout / lỗi kết nối / 429 / 5xx: thử lại với backoff có jitter, tối đa `max_attempts`;
      hết lượt thì raise `HttpError`.
    - 4xx khác 429: fail fast, **trả về response** để caller đọc mã lỗi của IdP/vendor.
    """

    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        max_attempts: int = 3,
        backoff_base_s: float = 0.2,
        backoff_max_s: float = 5.0,
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._client = httpx.AsyncClient(
            timeout=timeout_s, headers=dict(headers or {}), transport=transport
        )
        self._max_attempts = max_attempts
        self._base = backoff_base_s
        self._max = backoff_max_s
        self._sleep = sleep
        self._rng = rng

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(self._max, max(0.0, retry_after))
        return self._rng() * min(self._max, self._base * (2 ** (attempt - 1)))

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, self._max_attempts + 1):
            retry_after: float | None = None
            try:
                resp = await self._client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                err = HttpError("timeout", retryable=True)
            except httpx.TransportError:
                err = HttpError("connection", retryable=True)
            else:
                if resp.status_code != 429 and resp.status_code < 500:
                    return resp
                err = HttpError(f"http_{resp.status_code}", retryable=True, status=resp.status_code)
                if resp.status_code == 429:
                    try:
                        retry_after = float(resp.headers.get("retry-after", ""))
                    except ValueError:
                        retry_after = None
            if attempt == self._max_attempts:
                raise err from None
            await self._sleep(self._delay(attempt, retry_after))
        raise AssertionError("unreachable")  # pragma: no cover

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["HttpError", "RetryingHttpClient"]
