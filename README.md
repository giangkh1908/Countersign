# AI_EXAMPLE — Trợ lý AI nội bộ có trích dẫn kiểm chứng được

Trợ lý trả lời câu hỏi từ tài liệu công ty, mỗi câu kèm trích dẫn trỏ tới đoạn nguồn cụ thể, phân quyền theo người dùng ở tầng DB (RLS). Stack: LangGraph (agent), MCP (docs-mcp), gateway LLM mỏng, Keycloak + BFF + SPA React/TS. Corpus chính: 19 luật Việt Nam từ vbpl.vn ([`data/SOURCES.md`](data/SOURCES.md)). Phạm vi: [ADR-006](docs/adr/ADR-006-scope-rag-citations.md), [ADR-007](docs/adr/ADR-007-actions-cache-observability.md).

## Trạng thái

M0, M1 xong (walking skeleton chạy đầu-cuối trên compose). Đang ở R0. Chưa làm: embedder thật và loader luật (R1), trích dẫn kiểm chứng (R2), tạo ticket và `notify-mcp` (A1), cache và trace (Q1). Chưa có số đo RAM. Lộ trình: [`docs/ROADMAP.md`](docs/ROADMAP.md).

Compose mặc định: postgres, redis-state, keycloak, migrate, mock-provider, gateway, docs-mcp, agent, bff. Profile: `tickets` (tickets-mcp, approval-signer), `obs` (prometheus, grafana). Không bật `tickets` thì agent tự tắt route ticket và các API phê duyệt của BFF trả `503 upstream_unavailable`.

## Yêu cầu

uv, Python 3.12, Node 22, pnpm, Docker (compose v2). Windows: dùng Git Bash hoặc WSL cho script `.sh`. Git Bash không kèm `make`; không có `make` thì chạy lệnh tương ứng trong `Makefile`, ví dụ `make up` là `docker compose up -d --build --wait`.

## Quickstart

1. Thêm vào file hosts: `127.0.0.1 keycloak.acme.local`
2. `make setup`
3. `make secrets` — sinh `./secrets/*` và `.env` (đã gitignore)
4. `make up` — build lần đầu mất vài phút. Đã có volume Postgres cũ thì chạy `docker compose down -v` trước: SQL khởi tạo chỉ chạy trên volume trống, volume cũ sẽ thiếu schema mới.
5. Nạp seed, **phải làm trước bước 6** (bảng `departments` chỉ có dữ liệu sau bước này):
   `uv run python -m data.generator` rồi `bash data/load_seed.sh`
6. `bash scripts/bootstrap-gateway-keys.sh --restart` — tạo API key gateway cho agent và docs-mcp (cần phòng `IT` từ seed)
7. `bash scripts/smoke.sh`
8. Mở http://localhost:8300 (đăng nhập qua Keycloak). Gateway mặc định dùng `mock-provider`; muốn LLM thật, điền `secrets/anthropic_api_key` rồi đổi `GW_PROVIDER_OVERRIDE` trong `.env` (compose mặc định `mock`; tên hợp lệ ở `packages/gateway/src/gateway/factory.py`).

Bật ticket: `docker compose --profile tickets up -d`. Dừng: `make down`. Log: `make logs`.

### Tài nguyên

Đo 2026-11-02 trên Docker Desktop (WSL2), tổng `docker stats` các container, dùng `mock-provider`, chưa có dữ liệu RAG thật:

| Trạng thái | RAM |
|---|---|
| Stack mặc định, rảnh | 1,2 GiB |
| Thêm profile `tickets`, rảnh | 1,3 GiB |
| Đỉnh khi chạy E2E đóng ticket | 1,4 GiB |

Keycloak chiếm khoảng 630 MiB. Số trên chưa tính Docker engine và cache của hệ điều hành.

### Ingest cho docs-mcp

Sau bước 5, nạp tài liệu vào kho tri thức:

```
uv run python -m mcp_docs.ingest [--corpus-dir data/generated] [--force]
```

Cần `DOCS_INGEST_DATABASE_URL` (role `kn_ingest`) trong môi trường. Ingest và truy vấn phải dùng cùng embedder (`DOCS_EMBEDDER`, hiện mặc định `fake_hash`); khác embedder thì vector không so sánh được, phải ingest lại với `--force`.

## Tải corpus luật

```
uv run --with beautifulsoup4 python -m data.vbpl
```

Ghi vào `data/raw/` (gitignore), khoảng 1 phút. Danh sách chọn: `data/vbpl/selection.json`. Loader nạp luật vào kho là việc của R1, chưa có.

## Kiểm thử

```
make lint        # ruff format --check + ruff check
make test        # pytest toàn workspace
make test-web    # vitest
make leak-grep   # kiểm kiến trúc (contracts §9.1 mục 8)
cd web && pnpm e2e   # Playwright, cần stack đang chạy và `playwright install`
```

## Cấu trúc repo

```
├─ packages/    # common, gateway, agent, bff, mcp_docs, mock_provider, mcp_tickets, approval_signer
├─ web/         # SPA Vite + React + TS (pnpm), Playwright trong web/e2e
├─ data/        # generator ACME giả lập, vbpl/ (tải luật), SOURCES.md
├─ eval/        # e2e/ (đóng ticket); bộ đánh giá RAG chưa có
├─ infra/       # keycloak, postgres, redis, prometheus, grafana
├─ scripts/     # gen-secrets, bootstrap-gateway-keys, smoke, leak-grep, backup, e2e-close-ticket
├─ docs/        # SOLUTION, ROADMAP, design/, adr/, research/
├─ docker-compose.yml, Dockerfile, Makefile, pyproject.toml (uv workspace)
```

## Tài liệu

- [`docs/design/contracts.md`](docs/design/contracts.md) — hợp đồng dùng chung, quy tắc Ports & Adapters (§9)
- [`docs/design/approval.md`](docs/design/approval.md), [`docs/design/rag-citations.md`](docs/design/rag-citations.md)
- [`docs/SOLUTION.md`](docs/SOLUTION.md), [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/adr/`](docs/adr/), [`docs/research/`](docs/research/)
- [`infra/README.md`](infra/README.md), [`data/README.md`](data/README.md), [`eval/README.md`](eval/README.md), [`web/README.md`](web/README.md)
