# acme-mcp-tickets

MCP server ticket: đọc, và ghi qua intent ký + approval token (WYSIWYS, contracts §4.1).

- Import: `mcp_tickets`; cổng: 8102; mạng: mạng `backend` (tickets-mcp).
- Chạy: `uvicorn mcp_tickets.main:app` (Dockerfile: `uv sync --package acme-mcp-tickets`, docs/design/04-infra-data-eval.md §1.5).
- Thiết kế: docs/design/02-mcp-servers.md, 05-approval-flow.md; hợp đồng: docs/design/00-contracts.md §1, §7, §9.
- Trạng thái: khung (skeleton), chưa có logic nghiệp vụ.
