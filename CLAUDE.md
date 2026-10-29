# AI_EXAMPLE — Nền tảng trợ lý AI nội bộ doanh nghiệp

Đề tài: LangGraph điều phối agent, MCP kết nối hệ thống nghiệp vụ, LLM Gateway tự phát triển (bảo mật + kiểm soát chi phí).

## Đội agent
| Vai trò | Agent | Model | Nhiệm vụ |
|---|---|---|---|
| Đầu não | main session / `orchestrator` | Opus | Lập kế hoạch, chia việc, review |
| Thợ | `worker` | Sonnet | Viết/sửa code, build, test |
| Đọc | `reader` | Haiku | Đọc, tìm kiếm, tóm tắt, tra web (read-only) |

Quy tắc: đọc/tìm → `reader`; code → `worker`; quyết định → orchestrator.
Định nghĩa agent nằm trong `.claude/agents/`.

## Quy tắc code (BẮT BUỘC): Ports & Adapters
Chi tiết ở `docs/design/00-contracts.md` §9. Tóm tắt:
- Mọi tích hợp bên ngoài (LLM provider, embedding, PII, guard, cache, IdP, ticket system, vector store, MCP SDK...) nằm sau một **port `abc.ABC`** đặt tên theo năng lực. Adapter và fake kế thừa port một cách tường minh.
- `ports/` không import vendor; mỗi vendor một file trong `adapters/`; `factory.py` dùng **registry dict + lazy import** để chọn vendor theo config, không dùng chuỗi `if/elif`.
- Retry, circuit breaker, fallback, metrics: dùng **decorator** cùng port. Plumbing HTTP dùng chung qua composition (`RetryingHttpClient`).
- Business logic (`services/`, `api/`) chỉ import port và factory. Leak-grep (§9.1 mục 8) phải không có kết quả nào.
- Không bọc hạ tầng cố định (Postgres, Redis client, FastAPI, LangGraph) hay chuẩn mở (OpenAI-compatible API, OIDC, OTel).
- Thêm vendor mới = thêm file, **không sửa** code nghiệp vụ. Nếu buộc phải sửa thì thiết kế đang sai, cần báo orchestrator.

## Tài liệu
- `docs/design/00-contracts.md` — hợp đồng dùng chung (nguồn chân lý)
- `docs/design/DECISIONS-v1.2.md` — các quyết định v1.2 (thắng khi mâu thuẫn)
- `docs/design/01..06` — thiết kế chi tiết: 01 gateway, 02 MCP, 03 agent/UI, 04 hạ tầng/dữ liệu/đánh giá, 05 luồng phê duyệt, 06 policy-sidecar
- `docs/SOLUTION.md` — giải pháp & kiến trúc
- `docs/ROADMAP.md` — milestone M0–M7
- `docs/adr/`, `docs/reviews/` — ADR và review
- `docs/research/` — kết quả research
