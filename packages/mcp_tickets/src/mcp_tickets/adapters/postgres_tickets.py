"""Adapter `postgres` cho port `TicketRepository` (psycopg 3 async, role `tk_app`, RLS FORCE).

Mỗi lời gọi mở một transaction và `set_config('app.*', ..., true)` (= SET LOCAL) từ principal
trước mọi truy vấn: thiếu ngữ cảnh => RLS không khớp dòng nào (fail-closed). `commit_write` ghi
UPDATE + `ticket_events` + `tool_audit` (hash-chain) trong CÙNG transaction; lỗi bất kỳ => rollback cả ba.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import psycopg
from acme_common.adapters.audit_pg import append_audit
from acme_common.ports import Principal
from acme_common.services.audit_chain import AuditKeyring
from psycopg import errors as pgerr
from psycopg.types.json import Jsonb

from ..ports import (
    AppliedOp,
    Approval,
    Audience,
    Comment,
    DuplicateIntent,
    Intent,
    RepositoryRolledBack,
    RepositoryUnavailable,
    Ticket,
    TicketConflict,
    TicketRepository,
    UnsupportedOperation,
)
from ..ports.types import parse_iso

log = logging.getLogger("acme.mcp_tickets.postgres")

_COLS = (
    "code, title, description, status, priority, category, requester_sub, requester_dept, "
    "assignee_sub, assignee_dept, classification, created_at, updated_at, closed_at, closed_by, "
    "resolution"
)
_TCOLS = ", ".join(f"t.{c.strip()}" for c in _COLS.split(","))
_COMMENT_COLS = "c.id, c.author_sub, c.body, c.internal, c.created_at"
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_OP_ACTION = {"close_ticket": "close", "create_ticket": "create"}


def _ticket(row: Sequence[Any]) -> Ticket:
    return Ticket(
        code=row[0],
        title=row[1],
        description=row[2],
        status=row[3],
        priority=row[4],
        category=row[5],
        requester_sub=row[6],
        requester_dept=row[7],
        assignee_sub=row[8],
        assignee_dept=row[9],
        classification=int(row[10]),
        created_at=row[11],
        updated_at=row[12],
        closed_at=row[13],
        closed_by=row[14],
        resolution=row[15],
    )


def tsquery_or(query: str) -> str:
    """OR các token chữ-số của câu hỏi; chỉ ký tự `\\w` nên không thể chèn toán tử tsquery."""
    toks = [t.lower() for t in _TOKEN_RE.findall(query)][:10]
    return " | ".join(toks)


class PostgresTicketRepository(TicketRepository):
    def __init__(
        self, dsn: str, keyring: AuditKeyring, *, connect_timeout_s: int = 5, audit_actor: str = ""
    ) -> None:
        self._dsn = dsn
        self._keyring = keyring
        self._timeout = connect_timeout_s
        self._actor = audit_actor or "tickets-mcp"

    # --- hạ tầng ---
    @asynccontextmanager
    async def _tx(self, p: Principal) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        try:
            conn = await psycopg.AsyncConnection.connect(
                self._dsn, connect_timeout=self._timeout, autocommit=False
            )
        except psycopg.Error:
            raise RepositoryUnavailable("connect") from None
        try:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.sub', %s, true), set_config('app.depts', %s, true), "
                    "set_config('app.roles', %s, true)",
                    (p.sub, ",".join(p.dept), ",".join(p.roles)),
                )
                yield conn
        finally:
            await conn.close()

    @staticmethod
    def _wrap_read_errors(e: psycopg.Error) -> RepositoryUnavailable:
        return RepositoryUnavailable("query", retryable=isinstance(e, psycopg.OperationalError))

    # --- đọc ---
    async def get(self, code: str, principal: Principal) -> Ticket | None:
        try:
            async with self._tx(principal) as conn:
                cur = await conn.execute(f"SELECT {_COLS} FROM tickets WHERE code = %s", (code,))
                row = await cur.fetchone()
        except psycopg.Error as e:
            raise self._wrap_read_errors(e) from None
        return _ticket(row) if row else None

    async def read_for_intent(self, code: str, principal: Principal) -> Ticket | None:
        return await self.get(code, principal)  # timestamptz của psycopg giữ micro-giây

    async def comments(self, code: str, principal: Principal, limit: int) -> list[Comment]:
        try:
            async with self._tx(principal) as conn:
                cur = await conn.execute(
                    f"SELECT {_COMMENT_COLS} FROM ticket_comments c JOIN tickets t "
                    "ON t.id = c.ticket_id WHERE t.code = %s ORDER BY c.id DESC LIMIT %s",
                    (code, limit),
                )
                rows = await cur.fetchall()
        except psycopg.Error as e:
            raise self._wrap_read_errors(e) from None
        return [Comment(r[0], r[1], r[2], r[3], r[4]) for r in reversed(rows)]

    async def list_for(
        self,
        principal: Principal,
        relation: str,
        statuses: Sequence[str],
        limit: int,
        cursor: str | None,
    ) -> list[Ticket]:
        rel = {
            "requested": "requester_sub = %(sub)s",
            "assigned": "assignee_sub = %(sub)s",
            "both": "(requester_sub = %(sub)s OR assignee_sub = %(sub)s)",
        }.get(relation)
        if rel is None:
            raise UnsupportedOperation("relation")
        params: dict[str, Any] = {"sub": principal.sub, "limit": limit}
        where = [rel]
        if statuses:
            where.append("status = ANY(%(statuses)s)")
            params["statuses"] = list(statuses)
        if cursor:
            try:
                params["cursor"] = int(cursor)
            except ValueError:
                raise UnsupportedOperation("cursor") from None
            where.append("id < %(cursor)s")
        sql = (
            f"SELECT id, {_COLS} FROM tickets WHERE {' AND '.join(where)} "
            "ORDER BY id DESC LIMIT %(limit)s"
        )
        return await self._select_tickets(principal, sql, params)

    async def search(
        self,
        principal: Principal,
        query: str,
        scope: str,
        statuses: Sequence[str],
        priorities: Sequence[str],
        limit: int,
    ) -> list[Ticket]:
        tsq = tsquery_or(query)
        if not tsq:
            return []
        params: dict[str, Any] = {"q": tsq, "limit": limit, "sub": principal.sub}
        doc = "to_tsvector('simple', title || ' ' || description)"
        where = [f"{doc} @@ to_tsquery('simple', %(q)s)"]
        if scope == "mine":
            where.append("(requester_sub = %(sub)s OR assignee_sub = %(sub)s)")
        if statuses:
            where.append("status = ANY(%(statuses)s)")
            params["statuses"] = list(statuses)
        if priorities:
            where.append("priority = ANY(%(priorities)s)")
            params["priorities"] = list(priorities)
        sql = (
            f"SELECT id, {_COLS} FROM tickets WHERE {' AND '.join(where)} "
            f"ORDER BY ts_rank_cd({doc}, to_tsquery('simple', %(q)s)) DESC, id DESC LIMIT %(limit)s"
        )
        return await self._select_tickets(principal, sql, params)

    async def _select_tickets(
        self, principal: Principal, sql: str, params: Mapping[str, Any]
    ) -> list[Ticket]:
        try:
            async with self._tx(principal) as conn:
                cur = await conn.execute(sql, params)  # type: ignore[arg-type]
                rows = await cur.fetchall()
        except psycopg.Error as e:
            raise self._wrap_read_errors(e) from None
        return [replace(_ticket(r[1:]), cursor=str(r[0])) for r in rows]

    async def ticket_audience(self, draft: Mapping[str, Any]) -> Audience:
        # Hàm SQL thuần (không đọc bảng): chạy bằng ngữ cảnh rỗng vẫn đúng.
        empty = Principal("", (), None, frozenset(), 0.0)
        try:
            async with self._tx(empty) as conn:
                cur = await conn.execute(
                    "SELECT min_clearance, dept_set FROM acme.ticket_audience(%s)",
                    (Jsonb(dict(draft)),),
                )
                row = await cur.fetchone()
        except psycopg.Error as e:
            raise self._wrap_read_errors(e) from None
        assert row is not None
        return Audience(int(row[0]), frozenset(row[1] or ()))

    # --- ghi ---
    async def commit_write(
        self, intent: Intent, approval: Approval, principal: Principal
    ) -> AppliedOp:
        if intent.op not in _OP_ACTION:
            raise UnsupportedOperation(intent.op)
        reached_commit = False
        try:
            async with self._tx(principal) as conn:
                if intent.op == "create_ticket":
                    applied = await self._create_ticket(conn, intent, approval, principal)
                else:
                    applied = await self._close_ticket(conn, intent, approval, principal)
                reached_commit = True  # từ đây lỗi chỉ có thể đến từ COMMIT: kết quả không xác định
        except TicketConflict:
            raise
        except RepositoryUnavailable as e:
            if e.kind == "connect":  # chưa mở được transaction => chắc chắn chưa ghi gì
                raise RepositoryRolledBack from None
            raise
        except (pgerr.UniqueViolation, pgerr.ExclusionViolation):
            raise DuplicateIntent from None
        except psycopg.Error as e:
            if reached_commit:
                raise RepositoryUnavailable("commit_unknown") from None
            log.warning("commit_write rolled back: %s", type(e).__name__)
            raise RepositoryRolledBack from None
        return applied

    async def _close_ticket(
        self,
        conn: psycopg.AsyncConnection[Any],
        intent: Intent,
        approval: Approval,
        principal: Principal,
    ) -> AppliedOp:
        expected = parse_iso(intent.expected_updated_at) if intent.expected_updated_at else None
        if expected is None or not intent.ticket_code:
            raise RepositoryRolledBack
        cur = await conn.execute(
            f"UPDATE tickets SET status = 'closed', closed_at = now(), closed_by = %s, "
            f"resolution = %s, updated_at = now() "
            f"WHERE code = %s AND updated_at = %s AND status <> 'closed' RETURNING id, {_COLS}",
            (principal.sub, intent.args["resolution"], intent.ticket_code, expected),
        )
        row = await cur.fetchone()
        if row is None:
            raise TicketConflict  # 0 dòng: ticket đã đổi (hoặc RLS chặn); transaction rollback
        ticket_id, ticket = row[0], _ticket(row[1:])
        return await self._record_event(conn, ticket_id, ticket, intent, approval, principal)

    async def _create_ticket(
        self,
        conn: psycopg.AsyncConnection[Any],
        intent: Intent,
        approval: Approval,
        principal: Principal,
    ) -> AppliedOp:
        a = intent.args
        # `code` rỗng => trigger `ticket_code_default` cấp từ id (chỉ cấp lúc commit)
        cur = await conn.execute(
            f"INSERT INTO tickets (code, title, description, status, priority, category, "
            f"requester_sub, requester_dept, assignee_dept, classification) "
            f"VALUES ('', %s, %s, 'open', %s, %s, %s, %s, %s, %s) RETURNING id, {_COLS}",
            (
                a["title"],
                a["body"],
                a["priority"],
                a["category"],
                principal.sub,
                principal.dept[0],
                a["assignee_dept"],
                a["classification"],
            ),
        )
        row = await cur.fetchone()
        if row is None:
            raise RepositoryRolledBack
        ticket = _ticket(row[1:])
        return await self._record_event(
            conn,
            row[0],
            ticket,
            replace(intent, target={**intent.target, "ticket_code": ticket.code}),
            approval,
            principal,
        )

    async def _record_event(
        self,
        conn: psycopg.AsyncConnection[Any],
        ticket_id: int,
        ticket: Ticket,
        intent: Intent,
        approval: Approval,
        principal: Principal,
    ) -> AppliedOp:
        cur = await conn.execute(
            "INSERT INTO ticket_events (ticket_id, actor_sub, on_behalf_of, action, approval_jti, "
            "intent_id, intent_sha256, before, after) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                ticket_id,
                principal.sub,
                _OP_ACTION[intent.op],
                uuid.UUID(approval.jti),
                uuid.UUID(intent.intent_id),
                intent.sha256,
                Jsonb(intent.before),
                Jsonb(intent.after),
            ),
        )
        event_id = int((await cur.fetchone())[0])  # type: ignore[index]
        await append_audit(
            conn,
            "tool_audit",
            {
                "ts": ticket.updated_at,
                "actor_type": "service",
                "actor_id": self._actor,
                "end_user_sub": principal.sub,
                "action": "ticket.commit",
                "resource": f"tickets:{intent.ticket_code}",
                "decision": "allow",
                "details": {
                    "op": intent.op,
                    "ticket_code": intent.ticket_code,
                    "event_id": event_id,
                    "approval_jti": approval.jti,
                    "intent_sha256": intent.sha256,
                    "tables_written": ["tickets", "ticket_events", "tool_audit"],
                },
                "intent_id": intent.intent_id,
            },
            self._keyring,
        )
        return AppliedOp(
            op=intent.op,
            ticket_code=intent.ticket_code,
            event_id=event_id,
            approval_jti=approval.jti,
            ticket=ticket,
        )

    async def find_applied(self, intent_id: str, principal: Principal) -> AppliedOp | None:
        try:
            iid = uuid.UUID(intent_id)
        except ValueError:
            return None
        try:
            async with self._tx(principal) as conn:
                cur = await conn.execute(
                    f"SELECT e.id, e.action, e.approval_jti, {_TCOLS} FROM ticket_events e "
                    "JOIN tickets t ON t.id = e.ticket_id WHERE e.intent_id = %s",
                    (iid,),
                )
                row = await cur.fetchone()
        except psycopg.Error as e:
            raise self._wrap_read_errors(e) from None
        if row is None:
            return None
        op = next((k for k, v in _OP_ACTION.items() if v == row[1]), row[1])
        return AppliedOp(
            op=op,
            ticket_code=row[3],
            event_id=int(row[0]),
            approval_jti=str(row[2]) if row[2] else None,
            ticket=_ticket(row[3:]),
        )
