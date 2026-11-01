"""Port `ConversationRepository`: sổ cái thread của người dùng (bảng `conversations`, contracts §5).

Thread của người khác hoặc đã xoá trả `None` (không lộ tồn tại).
Adapter v1: `postgres`, `memory` (test/dev).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Conversation:
    thread_id: str
    user_sub: str
    title: str | None
    created_at: datetime
    last_active_at: datetime


class ConversationRepository(abc.ABC):
    @abc.abstractmethod
    async def create(self, user_sub: str, title: str | None) -> Conversation: ...

    @abc.abstractmethod
    async def get(self, thread_id: str, user_sub: str) -> Conversation | None: ...

    @abc.abstractmethod
    async def list(self, user_sub: str, limit: int) -> list[Conversation]: ...

    @abc.abstractmethod
    async def touch(self, thread_id: str) -> None: ...

    @abc.abstractmethod
    async def mark_deleted(self, thread_id: str, user_sub: str) -> bool: ...
