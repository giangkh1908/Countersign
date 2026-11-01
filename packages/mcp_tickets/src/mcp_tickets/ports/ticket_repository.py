"""Port `TicketRepository` (contracts §9.2).

Nguồn ticket: adapter `postgres` (RLS là lớp phòng thủ thêm); mở rộng: jira, zendesk, glpi.
`TicketService` + `services/policy.py` phải đủ an toàn kể cả khi adapter KHÔNG có RLS.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from typing import Any

from acme_common.ports import Principal

from .types import AppliedOp, Approval, Audience, Comment, Intent, Ticket


class TicketRepository(abc.ABC):
    @abc.abstractmethod
    async def get(self, code: str, principal: Principal) -> Ticket | None:
        """`None` nếu không có hoặc người gọi không thấy."""

    @abc.abstractmethod
    async def comments(self, code: str, principal: Principal, limit: int) -> list[Comment]:
        """Comment mới nhất `limit` cái, cũ → mới. Adapter có thể đã lọc `internal`; service lọc lại."""

    @abc.abstractmethod
    async def list_for(
        self,
        principal: Principal,
        relation: str,
        statuses: Sequence[str],
        limit: int,
        cursor: str | None,
    ) -> list[Ticket]:
        """`relation` ∈ requested|assigned|both; mới nhất trước; `cursor` mờ đục do adapter cấp."""

    @abc.abstractmethod
    async def search(
        self,
        principal: Principal,
        query: str,
        scope: str,
        statuses: Sequence[str],
        priorities: Sequence[str],
        limit: int,
    ) -> list[Ticket]:
        """`scope` ∈ mine|visible."""

    @abc.abstractmethod
    async def read_for_intent(self, code: str, principal: Principal) -> Ticket | None:
        """Như `get` nhưng `updated_at` đủ micro-giây (dùng cho `expected_updated_at`)."""

    @abc.abstractmethod
    async def ticket_audience(self, draft: Mapping[str, Any]) -> Audience:
        """Đối tượng sẽ thấy bản nháp (SQL `acme.ticket_audience`); dùng cho cờ `possible_downgrade`."""

    @abc.abstractmethod
    async def commit_write(
        self, intent: Intent, approval: Approval, principal: Principal
    ) -> AppliedOp:
        """Thực thi MỘT intent đã duyệt trong 1 transaction (UPDATE + ticket_events + audit).

        Raise `TicketConflict` (0 dòng khớp `expected_updated_at`), `DuplicateIntent`,
        `RepositoryRolledBack` (rollback chắc chắn), `RepositoryUnavailable` (không xác định).
        """

    @abc.abstractmethod
    async def find_applied(self, intent_id: str, principal: Principal) -> AppliedOp | None:
        """Tra `ticket_events.intent_id` (idempotency, khôi phục `committing`)."""
