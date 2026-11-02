"""Port `IntentIssuer` (contracts §9.2): ký, lưu và chuyển trạng thái intent.

Chuyển trạng thái phải NGUYÊN TỬ (Lua/WATCH); không có `set_status` tự do.
Máy trạng thái duy nhất: `pending -> committing -> committed | failed` (docs/design/approval.md §2.3).
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any, Literal

from .intent_types import CasResult, Draft, SignedIntent, StoredIntent
from .types import Principal


class IntentIssuer(abc.ABC):
    @abc.abstractmethod
    async def issue(
        self, op: str, args: Mapping[str, Any], principal: Principal, draft: Draft
    ) -> SignedIntent:
        """Dựng payload (`args_canonical` từ `args` đã chuẩn hoá), ký, lưu `pending`.

        Raise `ToolError(invalid_argument)` nếu payload vượt giới hạn kích thước.
        """

    @abc.abstractmethod
    async def load(self, intent_id: str) -> StoredIntent | None:
        """`None` nếu key không tồn tại. Verify lại chữ ký; hỏng => `IntentInvalid`."""

    @abc.abstractmethod
    async def begin_commit(self, intent_id: str, jti: str) -> CasResult:
        """CAS `pending -> committing`, ghi `owner_jti`. `status="owned"` nếu thắng."""

    @abc.abstractmethod
    async def finish_commit(
        self, intent_id: str, jti: str, new: Literal["committed", "failed"]
    ) -> bool:
        """Chỉ khi `status==committing` và `owner_jti==jti`."""

    @abc.abstractmethod
    async def recover_stale(
        self, intent_id: str, stale_owner_jti: str, new: Literal["committed", "failed"]
    ) -> bool:
        """Chỉ khi `committing`, `owner_jti` khớp và `updated_at` cũ hơn ngưỡng."""
