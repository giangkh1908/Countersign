# AI_EXAMPLE — Trợ lý AI nội bộ có trích dẫn kiểm chứng được

Trợ lý trả lời câu hỏi từ tài liệu công ty, mỗi câu kèm trích dẫn trỏ tới đoạn nguồn cụ thể, phân quyền theo người dùng ở tầng DB (RLS). Stack: LangGraph (agent), MCP (docs-mcp), gateway LLM mỏng, Keycloak + BFF + SPA React/TS. Corpus chính: 19 luật Việt Nam từ vbpl.vn ([`data/SOURCES.md`](data/SOURCES.md)). Phạm vi: [ADR-006](docs/adr/ADR-006-scope-rag-citations.md), [ADR-007](docs/adr/ADR-007-actions-cache-observability.md).

## Trạng thái

Xong: M0, M1, R0, R1 (embedding bge-m3 qua Ollama, mặc định vector thuần), R2 (trích dẫn kiểm chứng; judge cần LLM thật), A1 (tạo/đóng ticket, `notify-mcp` với adapter `fake` và `telegram`), trace/metric/canary của Q1. Chưa làm: cache (Q1), R3, R4. Lộ trình: [`docs/ROADMAP.md`](docs/ROADMAP.md).

Compose mặc định: postgres, redis-state, keycloak, migrate, mock-provider, gateway, docs-mcp, agent, bff. Profile: `tickets` (tickets-mcp, approval-signer), `notify` (notify-mcp, approval-signer), `obs` (tempo, prometheus, grafana). Không bật `tickets` thì agent tự tắt route ticket và các API phê duyệt của BFF trả `503 upstream_unavailable`.

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

E2E notify-mcp (cần profile `tickets` + `notify`): `bash scripts/e2e-notify.sh`. E2E đóng ticket: `bash scripts/e2e-close-ticket.sh`. E2E tạo ticket: `bash scripts/e2e-create-ticket.sh`. Kiểm rò rỉ 16 user: `bash scripts/e2e-leak-check.sh` (báo cáo ở `eval/results/`). Trong worktree đặt `SECRETS_DIR` trỏ về `secrets/` của repo chính (cả Playwright).

### Tài nguyên

Đo 2026-11-02 trên Docker Desktop (WSL2), tổng `docker stats` các container (lấy mẫu mỗi 2 giây), dùng `mock-provider`:

| Trạng thái | RAM |
|---|---|
| Stack mặc định, rảnh | 1,2 GiB |
| Thêm profile `tickets`, rảnh | 1,3 GiB |
| Đỉnh khi chạy E2E đóng ticket | 1,4 GiB |
| Thêm profile `obs` (Tempo, Prometheus, Grafana), rảnh, đo 2026-11-02 sau một câu hỏi | cộng thêm khoảng 0,3 GiB: Tempo 103 MiB, Grafana 157 MiB, Prometheus 51 MiB |
| Đỉnh khi chạy 20 câu hỏi qua luồng agent thật (kho đã ingest 2.072 chunk; số này đo với embedding `mock_hash`, chưa đo lại với Ollama) | 1,26 GiB (trung bình 1,24) |
| Đủ profile `tickets` + `notify` + `obs`, rảnh sau E2E và canary (một mẫu) | 1,95 GiB: notify-mcp 93 MiB, tickets-mcp 114 MiB, approval-signer 78 MiB, Keycloak 506 MiB, Tempo 227 MiB |

Keycloak chiếm khoảng 550 đến 630 MiB. Trong lượt 20 câu hỏi, CPU trung bình mỗi container dưới 10% và đỉnh cao nhất 48% (một lõi): bff 47%, keycloak 48%, docs-mcp 28%, agent 26%, gateway 26% (bff và agent gồm cả tiến trình `docker exec` của script đo). Câu hỏi đi qua `search_documents` thật (agent, docs-mcp, gateway, Postgres) nhưng LLM là `mock-provider` được kịch bản hoá để gọi công cụ tìm kiếm, nên số này không gồm chi phí của LLM thật. Số trên chưa tính Docker engine và cache của hệ điều hành.

### Ingest cho docs-mcp

Sau bước 5, nạp tài liệu vào kho tri thức:

```
uv run python -m mcp_docs.ingest [--corpus-dir data/generated] [--force]
```

Cần `DOCS_INGEST_DATABASE_URL` (role `kn_ingest`) trong môi trường. Ingest và truy vấn phải dùng cùng embedder (`DOCS_EMBEDDER`: mặc định ngoài compose là `fake_hash`, compose đặt `gateway_http`); khác embedder thì vector không so sánh được; đổi model thì ingest lại tự nạp lại (không cần `--force`), chỉ đổi cách chunk hoặc ACL mới cần ép.

### Embedding thật bằng Ollama (tuỳ chọn)

Mặc định gateway dùng `mock_hash` (không cần GPU, CI dùng cấu hình này). Để dùng embedding thật chạy trên máy host:

```
ollama pull bge-m3                       # 1024 chiều, giữ EMBED_DIM=1024
# .env:  GW_MODELS_CONFIG=/app/packages/gateway/config/models.ollama.yaml
docker compose up -d --build gateway docs-mcp
```

Gateway trong container tới Ollama qua `host.docker.internal:11434` (`extra_hosts` trong compose). Ollama mặc định chỉ nghe `127.0.0.1`; nếu gateway không tới được, đó là quyết định mở `OLLAMA_HOST` của bạn, repo không tự đổi. Sau khi đổi model, chạy lại ingest **không cần `--force`**: `index_sig` và `index_meta.embed_model` dùng id model thật (header `x-acme-model` gateway trả về), nên tài liệu tự nạp lại. Trên GTX 1650 4 GB, lô 32 chunk mất hàng chục giây; `timeout_s` và `max_attempts: 1` nằm trong `models.ollama.yaml`, phía docs-mcp là `DOCS_EMBED_TIMEOUT_S`.

## Tải corpus luật

```
uv run --with beautifulsoup4 python -m data.vbpl
```

Ghi vào `data/raw/` (gitignore), khoảng 1 phút. Danh sách chọn: `data/vbpl/selection.json`.

Nạp luật vào kho: sinh metadata ACL rồi ingest thư mục đó (loader `vbpl_articles`, Điều dài cắt theo khoản):

```
uv run python -m data.vbpl.metadata            # ghi data/raw/vbpl/documents.jsonl
uv run python -m mcp_docs.ingest --corpus-dir data/raw/vbpl
```

Đo 2026-11-02: 19 văn bản, 2.003 chunk; `mock_hash` khoảng 11 giây, `bge-m3` qua Ollama trên GTX 1650 4 GB khoảng 20 phút (1.216 giây, không timeout); ingest lần hai bỏ qua cả 19 văn bản. Bộ 30 tài liệu ACME nạp riêng bằng `--corpus-dir data/generated` (69 chunk; 22 giây với `bge-m3`).

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
