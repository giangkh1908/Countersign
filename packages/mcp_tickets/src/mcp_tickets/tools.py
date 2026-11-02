"""Khai báo `ToolSpec` và đăng ký tool. Chỉ gọi `TicketService`, không có nghiệp vụ."""

from __future__ import annotations

from typing import Any

from acme_common.mcp import CallerContext, ToolInvoker, ToolOutput
from acme_common.ports import ToolServerHost, ToolSpec

from .services.ticket_service import TicketService

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_CODE = {"type": "string", "pattern": "^TCK-[0-9]{6,}$"}
_STATUS = {"enum": ["open", "in_progress", "resolved", "closed"]}
_PRIORITY = {"enum": ["low", "medium", "high", "urgent"]}
_CATEGORY = {
    "enum": [
        "quote_support",
        "refund_request",
        "complaint",
        "feature_request",
        "leave_request",
        "payroll_query",
        "account_access",
        "other",
    ]
}
_DEPT = {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{1,31}$"}
_READ_HINTS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "$schema": SCHEMA_DRAFT,
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        out["required"] = required
    return out


def _list(item: dict[str, Any], max_items: int = 4) -> dict[str, Any]:
    return {"type": "array", "items": item, "maxItems": max_items, "uniqueItems": True}


SPECS: dict[str, ToolSpec] = {
    "list_my_tickets": ToolSpec(
        name="list_my_tickets",
        title="Ticket của tôi",
        description="Liệt kê ticket do tôi tạo hoặc được giao cho tôi, mới nhất trước.",
        input_schema=_obj(
            {
                "relation": {"enum": ["requested", "assigned", "both"], "default": "both"},
                "status": _list(_STATUS),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                "cursor": {"type": "string", "maxLength": 64},
            }
        ),
        annotations=_READ_HINTS,
        required_scopes=("tickets:read",),
        timeout_s=8,
        cost=1,
    ),
    "get_ticket": ToolSpec(
        name="get_ticket",
        title="Chi tiết ticket",
        description="Xem một ticket theo mã, kèm comment người dùng được phép thấy.",
        input_schema=_obj(
            {
                "code": _CODE,
                "include_comments": {"type": "boolean", "default": True},
                "comments_limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            ["code"],
        ),
        annotations=_READ_HINTS,
        required_scopes=("tickets:read",),
        timeout_s=8,
        cost=1,
    ),
    "search_tickets": ToolSpec(
        name="search_tickets",
        title="Tìm ticket",
        description="Tìm ticket (tiêu đề, mô tả) trong phạm vi người dùng được xem.",
        input_schema=_obj(
            {
                "query": {"type": "string", "minLength": 2, "maxLength": 200},
                "scope": {"enum": ["mine", "visible"], "default": "visible"},
                "status": _list(_STATUS),
                "priority": _list(_PRIORITY),
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
            },
            ["query"],
        ),
        annotations=_READ_HINTS,
        required_scopes=("tickets:read",),
        timeout_s=8,
        cost=1,
    ),
    "prepare_close_ticket": ToolSpec(
        name="prepare_close_ticket",
        title="Chuẩn bị đóng ticket",
        description=(
            "Chuẩn bị đóng ticket với nội dung giải quyết và trả về intent. KHÔNG đóng ticket. "
            "Hành động khó hoàn tác sau khi người dùng duyệt."
        ),
        input_schema=_obj(
            {"code": _CODE, "resolution": {"type": "string", "minLength": 5, "maxLength": 2000}},
            ["code", "resolution"],
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        required_scopes=("tickets:write",),
        timeout_s=8,
        cost=5,
    ),
    "prepare_create_ticket": ToolSpec(
        name="prepare_create_ticket",
        title="Chuẩn bị tạo ticket",
        description=(
            "Chuẩn bị tạo ticket mới và trả về intent. KHÔNG tạo ticket: ticket chỉ có sau khi "
            "người dùng duyệt và `commit_intent` chạy."
        ),
        input_schema=_obj(
            {
                "title": {"type": "string", "minLength": 3, "maxLength": 200},
                "body": {"type": "string", "minLength": 3, "maxLength": 4000},
                "category": _CATEGORY,
                "priority": {**_PRIORITY, "default": "medium"},
                "assignee_dept": _DEPT,
                "classification": {"type": "integer", "minimum": 0, "maximum": 3, "default": 1},
            },
            ["title", "body", "category", "assignee_dept"],
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        required_scopes=("tickets:write",),
        timeout_s=8,
        cost=5,
    ),
    "commit_intent": ToolSpec(
        name="commit_intent",
        title="Thực hiện thao tác đã được duyệt",
        description=(
            "Thực hiện đúng thao tác của một intent đã được người dùng duyệt. Nội dung thao tác lấy "
            "từ intent đã ký, không thể thay đổi ở bước này; `args` (nếu có) phải trùng nguyên văn "
            "với tham số đã duyệt."
        ),
        input_schema=_obj(
            {
                "intent_id": {"type": "string", "format": "uuid", "pattern": "^[0-9a-fA-F-]{36}$"},
                "approval_token": {"type": "string", "minLength": 20, "maxLength": 2048},
                "args": {"type": "object"},
            },
            ["intent_id", "approval_token"],
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        required_scopes=("tickets:write",),
        timeout_s=15,
        cost=5,
        requires_approval=True,
    ),
}


def register_tools(host: ToolServerHost, invoker: ToolInvoker, svc: TicketService) -> None:
    async def list_my_tickets(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.list_my_tickets(
            ctx.principal,
            a.get("relation", "both"),
            a.get("status", []),
            a.get("limit", 20),
            a.get("cursor"),
        )
        return ToolOutput(data, {"tables_read": ["tickets"], "rows_returned": len(data["tickets"])})

    async def get_ticket(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.get_ticket(
            ctx.principal,
            ctx.thread_id,
            a["code"],
            a.get("include_comments", True),
            a.get("comments_limit", 20),
        )
        return ToolOutput(
            data,
            {"tables_read": ["tickets", "ticket_comments"], "resource": a["code"], "tainted": True},
        )

    async def search_tickets(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.search_tickets(
            ctx.principal,
            a["query"],
            a.get("scope", "visible"),
            a.get("status", []),
            a.get("priority", []),
            a.get("limit", 10),
        )
        return ToolOutput(data, {"tables_read": ["tickets"], "rows_returned": len(data["tickets"])})

    async def prepare_close_ticket(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.prepare_close_ticket(ctx.principal, ctx.thread_id, a)
        return ToolOutput(
            data,
            {
                "intent_id": data["intent_id"],
                "tables_read": ["tickets"],
                "op": "close_ticket",
                "risk_flags": data["risk_flags"],
            },
        )

    async def prepare_create_ticket(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.prepare_create_ticket(ctx.principal, ctx.thread_id, a)
        return ToolOutput(
            data,
            {
                "intent_id": data["intent_id"],
                "tables_read": [],
                "op": "create_ticket",
                "risk_flags": data["risk_flags"],
            },
        )

    async def commit_intent(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.commit_intent(
            ctx.principal, a["intent_id"], a["approval_token"], a.get("args")
        )
        return ToolOutput(
            data,
            {
                "intent_id": a["intent_id"],
                "op": data["op"],
                "tables_written": ["tickets", "ticket_events", "tool_audit"],
            },
        )

    handlers = {
        "list_my_tickets": list_my_tickets,
        "get_ticket": get_ticket,
        "search_tickets": search_tickets,
        "prepare_close_ticket": prepare_close_ticket,
        "prepare_create_ticket": prepare_create_ticket,
        "commit_intent": commit_intent,
    }
    for name, spec in SPECS.items():
        host.register(spec, invoker.wrap(spec, handlers[name]))


def required_scopes_for(name: str) -> tuple[str, ...] | None:
    spec = SPECS.get(name)
    return spec.required_scopes if spec else None
