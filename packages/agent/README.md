# acme-agent

Điều phối agent bằng LangGraph; gọi LLM qua gateway, tool qua MCP; checkpoint mã hoá.

- Import: `agent`; cổng: 8200; mạng: mạng `backend` (agent).
- Chạy: `uvicorn agent.main:app` (Dockerfile: `uv sync --package acme-agent`, docs/design/04-infra-data-eval.md §1.5).
- Thiết kế: docs/design/03-agent-ui.md; hợp đồng: docs/design/00-contracts.md §1, §7, §9.
- Trạng thái: khung (skeleton), chưa có logic nghiệp vụ.
