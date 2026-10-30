"""Adapter `memory` của `ConversationRepository` (test/dev)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ..ports.conversations import Conversation, ConversationRepository


class MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self._rows: dict[str, Conversation] = {}
        self._deleted: set[str] = set()

    async def create(self, user_sub: str, title: str | None) -> Conversation:
        now = datetime.now(UTC)
        c = Conversation(str(uuid.uuid4()), user_sub, title, now, now)
        self._rows[c.thread_id] = c
        return c

    async def get(self, thread_id: str, user_sub: str) -> Conversation | None:
        c = self._rows.get(thread_id)
        if c is None or c.user_sub != user_sub or thread_id in self._deleted:
            return None
        return c

    async def list(self, user_sub: str, limit: int) -> list[Conversation]:
        rows = [
            c
            for c in self._rows.values()
            if c.user_sub == user_sub and c.thread_id not in self._deleted
        ]
        rows.sort(key=lambda c: c.last_active_at, reverse=True)
        return rows[:limit]

    async def touch(self, thread_id: str) -> None:
        c = self._rows.get(thread_id)
        if c:
            self._rows[thread_id] = Conversation(
                c.thread_id, c.user_sub, c.title, c.created_at, datetime.now(UTC)
            )

    async def mark_deleted(self, thread_id: str, user_sub: str) -> bool:
        if await self.get(thread_id, user_sub) is None:
            return False
        self._deleted.add(thread_id)
        return True
