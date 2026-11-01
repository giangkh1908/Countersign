# AI_EXAMPLE — Trợ lý AI nội bộ có trích dẫn kiểm chứng được

> Phạm vi mở rộng theo [ADR-007](docs/adr/ADR-007-actions-cache-observability.md): hành động qua MCP (ticket, báo cáo nhóm chat), phân quyền theo vai trò, cache, quan sát. Các phần này chưa làm, xem [`docs/ROADMAP.md`](docs/ROADMAP.md) (A1, Q1).

Trợ lý trả lời từ tài liệu công ty, mỗi câu kèm trích dẫn trỏ tới đoạn nguồn cụ thể, có phân quyền theo người dùng (ACL ở tầng DB). Stack: LangGraph (agent), MCP (docs-mcp), LLM Gateway mỏng tự phát triển, Keycloak + BFF + SPA React/TS. Phạm vi theo [ADR-006](docs/adr/ADR-006-scope-rag-citations.md).

Ba câu hỏi nghiên cứu:
1. **Truy xuất:** hybrid (vector + từ khoá) và rerank cải thiện recall@k bao nhiêu trên tài liệu tiếng Việt?
2. **Trích dẫn:** bước kiểm chứng sau sinh nâng citation precision và faithfulness bao nhiêu, đổi lại chi phí/độ trễ bao nhiêu?
3. **An toàn:** với RLS và spotlighting, tỉ lệ rò tài liệu trái quyền và tỉ lệ tấn công thành công (ASR) của tài liệu độc là bao nhiêu?

Corpus chính: 19 luật/bộ luật Việt Nam từ vbpl.vn (1.557 Điều), xem [`data/SOURCES.md`](data/SOURCES.md).

## Trạng thái

M0, M1 xong (walking skeleton chạy đầu-cuối trên compose). Đang ở R0 (thu gọn stack). Lộ trình R0–R4: [`docs/ROADMAP.md`](docs/ROADMAP.md).

Compose mặc định chạy: postgres, redis-state, redis-cache, keycloak, migrate, mock-provider, gateway, docs-mcp, agent, bff. Profile tuỳ chọn: `tickets` (tickets-mcp, approval-signer; luồng đóng ticket đóng băng), `sidecar`, `analytics`, `obs`, `seed`.

Bật luồng ticket: `docker compose --profile tickets up -d`. Không bật thì agent tự tắt route ticket (router chỉ còn docs / trả lời trực tiếp), BFF vẫn khoẻ và các API phê duyệt trả `503 upstream_unavailable`.

**Dự kiến (R0), chưa làm:** đo RAM/CPU lúc rảnh và khi chạy 20 câu hỏi, ghi bảng vào README (mục tiêu dưới 2,5 GB lúc rảnh). Chưa có số đo RAM thật.

## Yêu cầu

uv, Python 3.12, Node 22, pnpm, Docker (compose v2). Trên Windows dùng Git Bash hoặc WSL cho `make` và các script `.sh`.

## Quickstart (dev, trạng thái hiện tại)

1. Thêm vào file hosts: `127.0.0.1 keycloak.acme.local`
2. `make setup` — `uv sync` và `pnpm install` cho `web/`
3. `make secrets` — sinh `./secrets/*` và `.env` (đã gitignore); chi tiết ở [`infra/README.md`](infra/README.md)
4. `make up` — `docker compose up -d --build --wait` (build lần đầu mất vài phút)
5. Nạp seed ACME (bắt buộc: bảng `departments` chỉ có dữ liệu sau bước này): `uv run python -m data.generator` rồi `bash data/load_seed.sh`
6. `bash infra/scripts/bootstrap-gateway-keys.sh --restart` — tạo API key gateway cho agent và docs-mcp (cần phòng `IT` từ seed), restart hai service này
7. `bash scripts/smoke.sh` — kiểm các service đã khoẻ, gateway nhận chat và ghi `usage_events`
8. Mở http://localhost:8300 (BFF + SPA, đăng nhập qua Keycloak). Gateway mặc định dùng `mock-provider`; muốn LLM thật, điền khoá vào `secrets/anthropic_api_key` hoặc `secrets/gemini_api_key` và đặt `GW_PROVIDER_OVERRIDE` trong `.env`.

Dừng: `make down`. Xem log: `make logs`.

## Tải corpus luật

```
uv run --with beautifulsoup4 python -m data.vbpl
```

Ghi vào `data/raw/` (đã gitignore), khoảng 1 phút, nghỉ 3 giây giữa các request. Danh sách chọn: `data/vbpl/selection.json`. Nạp vào kho tri thức (loader `vbpl_articles`) là việc của R1, chưa có.

## Kiểm thử

```
make lint                  # ruff format --check + ruff check
make test                  # pytest (toàn workspace)
make test-web              # vitest (tương đương: cd web && pnpm test)
cd web && pnpm e2e         # Playwright, cần stack compose đang chạy và `playwright install`
make leak-grep             # kiểm kiến trúc (contracts §9.1 mục 8)
make eval                  # eval/ (chạy riêng)
uv run pytest data/tests   # test generator seed
```

## Cấu trúc repo

```
├─ pyproject.toml        # uv workspace root (ruff, pytest)
├─ docker-compose.yml    # + docker-compose.bench.yml (overlay bench)
├─ Dockerfile            # đa tầng, target theo service
├─ models.lock           # model ML (chỉ policy-sidecar, đóng băng)
├─ infra/                # keycloak, postgres init, redis, prometheus, grafana, scripts/
├─ web/                  # SPA Vite + React + TS (pnpm), Playwright trong web/e2e
├─ packages/             # common, gateway, agent, bff, mcp_docs, mock_provider (đang dùng)
│                        # mcp_tickets, approval_signer, mcp_analytics, policy_sidecar (đóng băng)
├─ data/                 # vbpl/ (tải luật), generator ACME giả lập, corpus độc, tập test PII
├─ eval/                 # bench, promptfoo, security, e2e; bộ đánh giá RAG: xem eval/README.md
├─ scripts/              # smoke.sh, leak-grep.sh, e2e-close-ticket.sh
└─ docs/                 # SOLUTION, ROADMAP, design/, adr/, research/, reviews/
```

## Ports & Adapters (bắt buộc)

Tích hợp bên ngoài nằm sau port `abc.ABC`; mỗi vendor một file `adapters/<vendor>.py`; `factory.py` chọn vendor bằng registry dict + lazy import; retry/breaker/fallback/metrics là decorator cùng port; `services/` và `api/` chỉ import port và factory. Thêm vendor = thêm file, không sửa nghiệp vụ. Chi tiết: [`docs/design/00-contracts.md`](docs/design/00-contracts.md) §9.

## Tài liệu

- [`docs/adr/ADR-006-scope-rag-citations.md`](docs/adr/ADR-006-scope-rag-citations.md) — phạm vi hiện hành
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — lộ trình R0–R4
- [`docs/SOLUTION.md`](docs/SOLUTION.md) — giải pháp và kiến trúc
- [`data/SOURCES.md`](data/SOURCES.md) — nguồn và giấy phép dữ liệu
- [`docs/design/`](docs/design/) — hợp đồng (`00-contracts.md`), quyết định (`DECISIONS-v1.2.md`), thiết kế 01–07; mỗi file có banner trạng thái phạm vi
- [`infra/README.md`](infra/README.md), [`eval/README.md`](eval/README.md), [`web/README.md`](web/README.md)
- [`docs/adr/`](docs/adr/), [`docs/reviews/`](docs/reviews/), [`docs/research/`](docs/research/)
