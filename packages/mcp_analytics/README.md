# acme-mcp-analytics

MCP server analytics chỉ đọc (tool có tham số, không SQL tự do trong v1).

- Import: `mcp_analytics`; cổng: 8103; mạng: mạng `backend` (analytics-mcp).
- Chạy: `uvicorn mcp_analytics.main:app` (Dockerfile: `uv sync --package acme-mcp-analytics`, docs/design/04-infra-data-eval.md §1.5).
- Thiết kế: docs/design/02-mcp-servers.md; hợp đồng: docs/design/00-contracts.md §1, §7, §9.
- Trạng thái: khung (skeleton), chưa có logic nghiệp vụ.
