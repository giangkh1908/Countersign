"""Factory của mcp_tickets: chọn adapter theo Settings (contracts §9.1 mục 5).

Quy tắc: registry dict + lazy import (import adapter bên trong loader), KHÔNG dùng chuỗi if/elif.
Tên lạ -> raise XxxNotConfigured kèm danh sách tên hợp lệ. Port: TicketRepository, IntentIssuer, ApprovalVerifier, ReplayGuard. ToolServerHost lấy từ acme_common (acme_common.factory.build_tool_server_host).
"""

from collections.abc import Callable

# TODO(M1): thêm loader cho từng port, ví dụ "pgvector_hybrid": _load_pgvector_hybrid
_REGISTRY: dict[str, Callable[..., object]] = {}
