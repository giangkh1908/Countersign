"""Port `IntentExecutor`: phần riêng của từng MCP trong luồng commit dùng chung.

`IntentCommitService` (services/intent_commit.py) lo thứ tự kiểm approval và máy trạng thái intent;
executor chỉ lo phân quyền lại và thực thi MỘT thao tác đã duyệt (ghi DB, gửi tin...).
"""

from __future__ import annotations

import abc
from typing import Any

from .intent_types import Approval, Intent
from .types import Principal


class ExecutionConflict(Exception):
    """Đối tượng đã đổi sau khi duyệt (`expected_updated_at` lệch) hoặc đã ở trạng thái cuối."""


class DuplicateIntent(Exception):
    """Vi phạm UNIQUE(intent_id) hoặc UNIQUE(approval_jti): intent này đã được áp dụng."""


class ExecutionRolledBack(Exception):
    """Chắc chắn chưa có tác dụng phụ. Intent có thể chuyển `failed`."""


class ExecutionUnavailable(Exception):
    """Kết quả không xác định (vd mất kết nối lúc COMMIT) hoặc không kết nối được."""


class IntentExecutor(abc.ABC):
    @abc.abstractmethod
    async def reauthorize(self, principal: Principal, intent: Intent) -> None:
        """Phân quyền lại với người gọi HIỆN TẠI (vai trò có thể đổi giữa prepare và commit).

        Raise `ToolError` (`forbidden`, `not_found`, `conflict`, `invalid_argument`). Không đốt `jti`.
        """

    @abc.abstractmethod
    async def execute(self, intent: Intent, approval: Approval, principal: Principal) -> Any:
        """Thực thi đúng MỘT lần trong một đơn vị nguyên tử. Raise `ExecutionConflict`,
        `DuplicateIntent`, `ExecutionRolledBack`, `ExecutionUnavailable`. Trả kết quả cho `commit`."""

    @abc.abstractmethod
    async def applied_details(self, intent_id: str, principal: Principal) -> dict[str, Any] | None:
        """Tra bản ghi idempotency của `intent_id`: `None` nếu chưa áp dụng, dict mô tả nếu rồi
        (đưa vào `details` của `approval_replayed`). Raise `ExecutionUnavailable` nếu không tra được."""
