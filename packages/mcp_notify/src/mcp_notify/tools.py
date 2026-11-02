"""Khai báo `ToolSpec` và đăng ký tool. Chỉ gọi `NotifyService`, không có nghiệp vụ."""

from __future__ import annotations

from typing import Any

from acme_common.mcp import CallerContext, ToolInvoker, ToolOutput
from acme_common.ports import ToolServerHost, ToolSpec

from .services.report_service import MAX_TEXT_CHARS, OP, NotifyService

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_SCOPES = ("notify:write",)  # một scope cho cả liệt kê lẫn gửi (chỉ có notify:write trong realm)


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


SPECS: dict[str, ToolSpec] = {
    "list_report_channels": ToolSpec(
        name="list_report_channels",
        title="Kênh báo cáo của tôi",
        description="Liệt kê bí danh các nhóm chat mà tôi được phép gửi báo cáo.",
        input_schema=_obj({}),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        required_scopes=_SCOPES,
        timeout_s=8,
        cost=1,
    ),
    "prepare_send_group_report": ToolSpec(
        name="prepare_send_group_report",
        title="Chuẩn bị gửi báo cáo vào nhóm",
        description=(
            "Chuẩn bị gửi một báo cáo văn bản thuần vào nhóm chat và trả về intent. KHÔNG gửi gì: tin "
            "chỉ đi sau khi người dùng duyệt và `commit_intent` chạy. Tin đã gửi không thu hồi được. "
            "Đặt `unverified_claims=true` nếu báo cáo có khẳng định chưa kiểm chứng được từ tài liệu."
        ),
        input_schema=_obj(
            {
                "channel": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,63}$"},
                "text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_CHARS},
                "unverified_claims": {"type": "boolean", "default": False},
            },
            ["channel", "text"],
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        required_scopes=_SCOPES,
        timeout_s=8,
        cost=5,
    ),
    "commit_intent": ToolSpec(
        name="commit_intent",
        title="Thực hiện thao tác đã được duyệt",
        description=(
            "Gửi đúng tin của một intent đã được người dùng duyệt. Nội dung lấy từ intent đã ký, không "
            "thể thay đổi ở bước này; `args` (nếu có) phải trùng nguyên văn với tham số đã duyệt. "
            "Tối đa một lần gửi cho mỗi intent."
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
            "openWorldHint": True,
        },
        required_scopes=_SCOPES,
        timeout_s=40,  # gồm các lần thử lại khi chắc chắn chưa gửi
        cost=5,
        requires_approval=True,
    ),
}


def register_tools(host: ToolServerHost, invoker: ToolInvoker, svc: NotifyService) -> None:
    async def list_report_channels(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.list_report_channels(ctx.principal)
        return ToolOutput(data, {"rows_returned": len(data["channels"])})

    async def prepare_send_group_report(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.prepare_send_group_report(ctx.principal, ctx.thread_id, a)
        return ToolOutput(
            data,
            {
                "intent_id": data["intent_id"],
                "op": OP,
                "resource": a["channel"],
                "risk_flags": data["risk_flags"],
            },
        )

    async def commit_intent(ctx: CallerContext, a: dict[str, Any]) -> ToolOutput:
        data = await svc.commit_intent(
            ctx.principal, ctx.thread_id, a["intent_id"], a["approval_token"], a.get("args")
        )
        return ToolOutput(
            data,
            {"intent_id": a["intent_id"], "op": OP, "resource": data.get("channel")},
        )

    handlers = {
        "list_report_channels": list_report_channels,
        "prepare_send_group_report": prepare_send_group_report,
        "commit_intent": commit_intent,
    }
    for name, spec in SPECS.items():
        host.register(spec, invoker.wrap(spec, handlers[name]))


def required_scopes_for(name: str) -> tuple[str, ...] | None:
    spec = SPECS.get(name)
    return spec.required_scopes if spec else None
