# AI_EXAMPLE — Nền tảng trợ lý AI nội bộ doanh nghiệp

Đề tài (`docs/adr/ADR-006-scope-rag-citations.md`, sửa bởi `ADR-007-actions-cache-observability.md`): trợ lý AI nội bộ trả lời từ tài liệu công ty, **trích dẫn kiểm chứng được**, thực hiện việc qua MCP (ticket, báo cáo nhóm chat), phân quyền theo vai trò, có cache và quan sát (log, trace, metric, eval). Nghiên cứu: truy xuất hybrid tiếng Việt, kiểm chứng trích dẫn sau sinh, rò rỉ trái quyền và prompt injection gián tiếp, cache an toàn theo quyền. Corpus: luật Việt Nam từ vbpl.vn (`data/SOURCES.md`).
Giữ: Keycloak + BFF + SPA, gateway mỏng, docs-mcp, tickets-mcp + approval-signer (profile `tickets`), agent LangGraph, quan sát (profile `obs`). Chưa làm: cache (Q1), notify-mcp (A1, profile `notify`). Không tạo placeholder, file rỗng hay thư mục cho tính năng chưa làm.

## Đội agent
| Vai trò | Agent | Model | Nhiệm vụ |
|---|---|---|---|
| Đầu não | main session / `orchestrator` | Opus | Lập kế hoạch, chia việc, review |
| Thợ | `worker` | Sonnet | Viết/sửa code, build, test |
| Đọc | `reader` | Haiku | Đọc, tìm kiếm, tóm tắt, tra web (read-only) |

Quy tắc: đọc/tìm → `reader`; code → `worker`; quyết định → orchestrator.
Định nghĩa agent nằm trong `.claude/agents/`.

## Quy tắc code (BẮT BUỘC): Ports & Adapters
Chi tiết ở `docs/design/contracts.md` §9. Tóm tắt:
- Mọi tích hợp bên ngoài (LLM provider, embedding, PII, guard, cache, IdP, ticket system, vector store, MCP SDK...) nằm sau một **port `abc.ABC`** đặt tên theo năng lực. Adapter và fake kế thừa port một cách tường minh.
- `ports/` không import vendor; mỗi vendor một file trong `adapters/`; `factory.py` dùng **registry dict + lazy import** để chọn vendor theo config, không dùng chuỗi `if/elif`.
- Retry, circuit breaker, fallback, metrics: dùng **decorator** cùng port. Plumbing HTTP dùng chung qua composition (`RetryingHttpClient`).
- Business logic (`services/`, `api/`) chỉ import port và factory. Leak-grep (§9.1 mục 8) phải không có kết quả nào.
- Không bọc hạ tầng cố định (Postgres, Redis client, FastAPI, LangGraph) hay chuẩn mở (OpenAI-compatible API, OIDC, OTel).
- Thêm vendor mới = thêm file, **không sửa** code nghiệp vụ. Nếu buộc phải sửa thì thiết kế đang sai, cần báo orchestrator.
- Frontend (`web/`, React + TS): một `src/api/client.ts` duy nhất (`request()`, `sse()`); component không gọi `fetch`; interface trong `src/api/types.ts`, test dùng fake/MSW. Token chỉ ở BFF, không bao giờ xuống trình duyệt.

## Tài liệu
- `docs/design/contracts.md` — hợp đồng dùng chung (nguồn chân lý); §9 là quy tắc Ports & Adapters
- `docs/design/approval.md` — luồng phê duyệt thao tác ghi
- `docs/design/rag-citations.md` — thiết kế RAG và trích dẫn
- `docs/design/actions-roles.md` — thiết kế A1: ticket, notify-mcp, ma trận quyền
- `docs/design/cache-observability.md` — thiết kế Q1: cache, trace, metric, canary
- `docs/SOLUTION.md` — giải pháp và kiến trúc
- `docs/ROADMAP.md` — milestone R0–R4, A1, Q1
- `docs/adr/` — quyết định kiến trúc
- `docs/research/` — kết quả research
