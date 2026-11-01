"""Agent ticket (tickets-mcp): tool đọc + `prepare_*`; ghi chỉ qua `commit_intent` sau khi duyệt."""

from __future__ import annotations

from ..ports.tool_provider import ServerAccess
from . import AgentSpec

_PROMPT = (
    "Bạn là trợ lý xử lý ticket nội bộ. Dùng get_ticket / list_my_tickets / search_tickets để xem. "
    "Khi người dùng muốn ĐÓNG ticket, gọi prepare_close_ticket(code, resolution): công cụ này chỉ "
    "chuẩn bị đề xuất, người dùng sẽ duyệt trên giao diện; bạn không thể tự thực hiện thay đổi. "
    "Mỗi lượt chỉ chuẩn bị một thao tác. Trả lời bằng tiếng Việt, ngắn gọn."
)


def load_ticket_spec(settings: object) -> AgentSpec:
    return AgentSpec(
        route="ticket",
        node_name="ticket_agent",
        description_vi="Xem, tìm hoặc đóng ticket hỗ trợ (mã dạng TCK-000123).",
        router_examples=(("Đóng ticket TCK-000123 giúp tôi", "ticket"),),
        system_prompt=_PROMPT,
        read=(
            ServerAccess(
                "tickets-mcp",
                frozenset({"get_ticket", "list_my_tickets", "search_tickets"}),
                ("tickets:read",),
            ),
        ),
        write_ops=frozenset({"close_ticket"}),
        write_audience="tickets-mcp",
        write_scopes=("tickets:write",),
        editable_fields={"close_ticket": frozenset({"resolution"})},
    )
