# acme-mcp-docs

MCP server tra cứu tài liệu nội bộ (RAG hybrid); tool chỉ đọc, có taint cho nội dung không tin cậy.

- Import: `mcp_docs`; cổng: 8101; mạng: mạng `backend` (docs-mcp).
- Chạy: `uvicorn mcp_docs.main:app` (Dockerfile: `uv sync --package acme-mcp-docs`, docs/design/04-infra-data-eval.md §1.5).
- Thiết kế: docs/design/02-mcp-servers.md; hợp đồng: docs/design/00-contracts.md §1, §7, §9.
- Trạng thái: khung (skeleton), chưa có logic nghiệp vụ.
