"""Port `KeyStore`: `lookup(prefix)`, `create`, `revoke`.

Adapter v1: `postgres` (L1 trong process + Postgres; chưa có L2 Redis và pub/sub thu hồi).
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import abc

from .types import KeyRecord, NewKey


class KeyStore(abc.ABC):
    @abc.abstractmethod
    async def lookup(self, prefix: str) -> KeyRecord | None:
        """None nếu prefix không tồn tại."""

    @abc.abstractmethod
    async def create(self, new: NewKey, actor: str) -> KeyRecord:
        """Raise `KeyAlreadyExists` khi trùng prefix."""

    @abc.abstractmethod
    async def revoke(self, key_id: str, actor: str, reason: str) -> None:
        """Raise `KeyNotFound` khi không có key (hoặc đã thu hồi)."""

    @abc.abstractmethod
    async def update_allowed_models(
        self, key_id: str, allowed_models: tuple[str, ...], actor: str
    ) -> None:
        """Thay danh sách model của key đang active. Raise `KeyNotFound` khi không có key active."""

    async def aclose(self) -> None:  # noqa: B027 - hook tuỳ chọn, không bắt buộc override
        """Đóng kết nối. Mặc định không làm gì."""
