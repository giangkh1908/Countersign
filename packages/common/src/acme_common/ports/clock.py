"""Port `Clock`: `now() -> datetime`, `monotonic()`.

Adapter v1 dự kiến: `system`; test: `FakeClock`.
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import abc
from datetime import datetime


class Clock(abc.ABC):
    @abc.abstractmethod
    def now(self) -> datetime:
        """Giờ UTC có tzinfo (ts audit, exp, TTL)."""

    @abc.abstractmethod
    def monotonic(self) -> float:
        """Giây đơn điệu (cửa sổ rate limit, timer degraded, TTL cache nội bộ)."""
