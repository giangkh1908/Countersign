"""Adapter `system` cho port `Clock`.
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from ..ports.clock import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()
