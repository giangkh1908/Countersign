"""Port `ReplayGuard`: tiêu thụ `jti` của approval đúng một lần."""

from __future__ import annotations

import abc


class ReplayGuard(abc.ABC):
    @abc.abstractmethod
    async def consume(self, jti: str, ttl_s: int) -> bool:
        """`True` = lần đầu (đã ghi nhận); `False` = đã dùng. Lỗi hạ tầng => `BackendUnavailable`."""
