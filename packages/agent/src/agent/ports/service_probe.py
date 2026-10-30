"""Port `ServiceProbe`: kiểm một dịch vụ phụ (MCP server tuỳ chọn) có sẵn sàng không.

Adapter v1: `http` (GET /healthz). Test dùng `FakeServiceProbe` (testing.py).
"""

from __future__ import annotations

import abc


class ServiceProbe(abc.ABC):
    @abc.abstractmethod
    async def is_reachable(self, url: str) -> bool:
        """True nếu dịch vụ ở `url` trả khoẻ. Không ném lỗi; mọi sự cố truyền tải => False."""
