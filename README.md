# AI_EXAMPLE — Trợ lý AI nội bộ có trích dẫn kiểm chứng được

Trợ lý trả lời câu hỏi từ tài liệu công ty, mỗi câu kèm trích dẫn trỏ tới đoạn nguồn cụ thể, phân quyền theo người dùng ở tầng DB (RLS). Stack: LangGraph (agent), MCP (docs-mcp), gateway LLM mỏng, Keycloak + BFF + SPA React/TS. Corpus chính: 19 luật Việt Nam từ vbpl.vn ([`data/SOURCES.md`](data/SOURCES.md)). Phạm vi: [ADR-006](docs/adr/ADR-006-scope-rag-citations.md), [ADR-007](docs/adr/ADR-007-actions-cache-observability.md).

## Chạy thử từ đầu (khoảng 15 phút)

Cần: Docker Desktop (compose v2), [uv](https://docs.astral.sh/uv/), Python 3.12, Node 22 + pnpm, một key [OpenRouter](https://openrouter.ai/keys) có số dư. Trên Windows chạy mọi lệnh trong **Git Bash** (hoặc WSL), ở thư mục gốc repo. Git Bash không có `make`: mỗi `make x` dưới đây có lệnh tương đương ghi kèm.

| Bước | Lệnh | Làm gì |
|---|---|---|
| 1 | Thêm dòng `127.0.0.1 keycloak.acme.local` vào file hosts (Windows: `C:\Windows\System32\drivers\etc\hosts`, mở Notepad bằng quyền Admin) | Trình duyệt và container cùng gọi Keycloak bằng một tên miền |
| 2 | `make setup` (= `uv sync --all-packages && cd web && pnpm install`) | Cài thư viện Python và web |
| 3 | `make secrets` (= `bash scripts/gen-secrets.sh`) | Sinh mật khẩu nội bộ vào `secrets/` và tạo `.env`. Cả hai đã gitignore |
| 4 | Mở `secrets/openrouter_api_key`, dán key OpenRouter, lưu | Key duy nhất cần điền: dùng chung cho chat, embedding và rerank |
| 5 | `make up` (= `docker compose up -d --build --wait`) | Build và chạy stack; lần đầu mất vài phút |
| 6 | `uv run python -m data.generator` rồi `bash data/load_seed.sh` | Sinh và nạp dữ liệu công ty giả ACME: phòng ban, 16 nhân viên, ticket. Phải chạy trước bước 7 |
| 7 | `bash scripts/bootstrap-gateway-keys.sh --restart` | Tạo API key nội bộ để agent và docs-mcp gọi gateway |
| 8 | `uv run --with beautifulsoup4 python -m data.vbpl` rồi `uv run python -m data.vbpl.metadata` | Tải 19 luật từ vbpl.vn vào `data/raw/` và gán quyền truy cập cho từng luật (khoảng 1 phút) |
| 9 | `bash scripts/ingest.sh` | Cắt đoạn, embed và nạp luật cùng tài liệu ACME vào kho tri thức (khoảng 2.000 đoạn, vài phút qua OpenRouter). Chạy lại thì tài liệu không đổi được bỏ qua |
| 10 | `bash scripts/set-password.sh hoa.ngo MatKhau@123` | Đặt mật khẩu đăng nhập cho user thử nghiệm (user seed không có mật khẩu sẵn) |
| 11 | `bash scripts/smoke.sh` | Kiểm nhanh các service |
| 12 | Mở http://localhost:8300, đăng nhập `hoa.ngo` / mật khẩu vừa đặt | Hỏi thử, ví dụ: "Người lao động làm đủ 12 tháng được nghỉ phép năm bao nhiêu ngày?" |

Gặp lỗi schema ở bước 5 khi máy đã từng chạy bản cũ: `docker compose down -v` (xoá volume Postgres) rồi chạy lại từ bước 5. SQL khởi tạo chỉ chạy trên volume trống.

### Thử phân quyền

Câu trả lời chỉ dùng tài liệu mà người hỏi được phép xem; DB lọc theo phòng ban và cấp độ mật (RLS). Đặt mật khẩu cho vài user khác nhau rồi hỏi cùng một câu:

| User | Phòng ban, cấp độ | Thấy |
|---|---|---|
| `hoa.ngo` | HR, 2 | Luật chung (thuế, doanh nghiệp...) và luật lao động |
| `an.nguyen` | SALES, 1 | Chỉ luật chung: hỏi về nghỉ phép năm sẽ không có nguồn |
| `nam.truong` | IT, 1 | Luật chung và nhóm luật công nghệ thông tin |
| `phuc.cao` | mọi phòng, 3 (management) | Gần như tất cả |

Đủ 16 user ở `data/generated/users.json`.

### Hằng ngày

| Việc | Lệnh |
|---|---|
| Bật lại stack | `make up` (dữ liệu giữ trong volume, không cần làm lại bước 6 đến 10) |
| Dừng | `make down` (= `docker compose down`) |
| Xem log | `make logs` hoặc `docker compose logs -f agent gateway` |
| Đổi model | Sửa `packages/gateway/config/models.yaml` rồi `docker compose up -d --build --wait gateway`. Đổi model embedding thì chạy lại `bash scripts/ingest.sh` |
| Nạp thêm tài liệu | `bash scripts/ingest.sh <thư-mục>` (thư mục nằm trong `data/`, có `documents.jsonl` khai báo ACL) |
| Chạy không tốn tiền (LLM giả) | Trong `.env` đặt `GW_PROVIDER_OVERRIDE=mock` và `GW_MODELS_CONFIG=/app/packages/gateway/tests/models.test.yaml`, rồi `make up`. Embedding giả không so sánh được với vector đã nạp, nên phải ingest lại |
| Sao lưu DB | `make backup` (= `bash scripts/backup.sh`, ghi vào `backups/`) |
| Bật ticket | `docker compose --profile tickets up -d --wait` |
| Bật trace, metric (Grafana :3000) | `docker compose --profile obs up -d --wait` |

## Trạng thái

Xong: M0, M1, R0, R1 (truy xuất hybrid, embedding `baai/bge-m3` qua OpenRouter), R2 (trích dẫn kiểm chứng), A1 (tạo/đóng ticket, `notify-mcp` với adapter `fake` và `telegram`), trace/metric/canary của Q1. Cache (Q1) có code và số đo RQ4 (`python -m eval.cache users|run|report|scan`). Chưa làm: R3 (ASR tầng LLM), R4. Lộ trình: [`docs/ROADMAP.md`](docs/ROADMAP.md).

Compose mặc định: postgres, redis-state, keycloak, migrate, mock-provider, gateway, docs-mcp, agent, bff; `.env` bật thêm profile `cache` (redis-cache). Profile khác: `tickets` (tickets-mcp, approval-signer), `notify` (notify-mcp, approval-signer), `obs` (tempo, prometheus, grafana). Không bật `tickets` thì agent tự tắt route ticket và các API phê duyệt của BFF trả `503 upstream_unavailable`.

E2E notify-mcp (cần profile `tickets` + `notify`): `bash scripts/e2e-notify.sh`. E2E đóng ticket: `bash scripts/e2e-close-ticket.sh`. E2E tạo ticket: `bash scripts/e2e-create-ticket.sh`. Kiểm rò rỉ 16 user: `bash scripts/e2e-leak-check.sh` (báo cáo ở `eval/results/`). Trong worktree đặt `SECRETS_DIR` trỏ về `secrets/` của repo chính (cả Playwright).

### Tài nguyên

Đo 2026-11-02 trên Docker Desktop (WSL2), tổng `docker stats` các container (lấy mẫu mỗi 2 giây), dùng `mock-provider`:

| Trạng thái | RAM |
|---|---|
| Stack mặc định, rảnh | 1,2 GiB |
| Thêm profile `tickets`, rảnh | 1,3 GiB |
| Đỉnh khi chạy E2E đóng ticket | 1,4 GiB |
| Thêm profile `obs` (Tempo, Prometheus, Grafana), rảnh, đo 2026-11-02 sau một câu hỏi | cộng thêm khoảng 0,3 GiB: Tempo 103 MiB, Grafana 157 MiB, Prometheus 51 MiB |
| Đỉnh khi chạy 20 câu hỏi qua luồng agent thật (kho đã ingest 2.072 chunk; số này đo với embedding `mock_hash`) | 1,26 GiB (trung bình 1,24) |
| Đủ profile `tickets` + `notify` + `obs`, rảnh sau E2E và canary (một mẫu) | 1,95 GiB: notify-mcp 93 MiB, tickets-mcp 114 MiB, approval-signer 78 MiB, Keycloak 506 MiB, Tempo 227 MiB |

Keycloak chiếm khoảng 550 đến 630 MiB. Trong lượt 20 câu hỏi, CPU trung bình mỗi container dưới 10% và đỉnh cao nhất 48% (một lõi): bff 47%, keycloak 48%, docs-mcp 28%, agent 26%, gateway 26% (bff và agent gồm cả tiến trình `docker exec` của script đo). Câu hỏi đi qua `search_documents` thật (agent, docs-mcp, gateway, Postgres) nhưng LLM là `mock-provider` được kịch bản hoá để gọi công cụ tìm kiếm, nên số này không gồm chi phí của LLM thật. Số trên chưa tính Docker engine và cache của hệ điều hành.

### Ingest cho docs-mcp

`scripts/ingest.sh` chạy `mcp_docs.ingest` trong một container tạm trên mạng Docker, vì Postgres không mở cổng ra host. Ingest và truy vấn phải dùng cùng embedder (compose đặt `DOCS_EMBEDDER=gateway_http`). Đổi model embedding thì chạy lại là đủ, tài liệu tự nạp lại; chỉ khi đổi cách chunk hoặc ACL mới cần `bash scripts/ingest.sh <thư-mục> --force`.

### Cấu hình: `.env` và `models.yaml`

Chỉ sửa hai chỗ: `.env` (vài biến compose nội suy, xem `.env.example`) và `packages/gateway/config/models.yaml` (alias model). Chat và embedding đều đi qua OpenRouter bằng một key `secrets/openrouter_api_key`: ba alias chat dùng DeepSeek V4.1 Flash, `acme-embed` dùng `baai/bge-m3` (1024 chiều, giữ `EMBED_DIM=1024`). Mỗi alias chat có thể khai `extra_body` (dict gửi kèm tới provider, gateway không diễn giải); hiện dùng `reasoning: {enabled: false}` để tắt reasoning của DeepSeek V4.1 Flash. Rerank tuỳ chọn (`DOCS_RERANK=gateway_rerank`) cũng qua OpenRouter (`qwen/qwen3-reranker-8b`). Không cần Ollama hay runtime local nào.

Chạy từng service ngoài Docker (`uv run`): `Settings` có `extra="ignore"` và giá trị mặc định, nên không cần liệt kê hết biến; secret đặt qua `<BIẾN>_FILE` trỏ tới `./secrets/<tên>`. Test và CI dùng cấu hình mock riêng `packages/gateway/tests/models.test.yaml` (chat giả, embedding `mock_hash`), không phụ thuộc OpenRouter; muốn dựng stack mock thì đặt `GW_PROVIDER_OVERRIDE=mock` và `GW_MODELS_CONFIG=/app/packages/gateway/tests/models.test.yaml`.

Sau khi đổi model embedding, chạy lại ingest **không cần `--force`**: `index_sig` và `index_meta.embed_model` dùng id model thật (header `x-acme-model` gateway trả về), nên tài liệu tự nạp lại. `timeout_s` của embedding nằm trong `models.yaml`, phía docs-mcp là `DOCS_EMBED_TIMEOUT_S`.

## Corpus luật

`python -m data.vbpl` tải về `data/raw/` (gitignore); danh sách chọn ở `data/vbpl/selection.json`. `python -m data.vbpl.metadata` ghi `data/raw/vbpl/documents.jsonl` (ACL từng luật). Loader `vbpl_articles` cắt theo Điều, Điều dài cắt theo khoản. Đo 2026-11-02: 19 văn bản, 2.003 chunk; bộ 30 tài liệu ACME (`data/generated`) thêm 69 chunk. Ingest lần hai bỏ qua mọi văn bản không đổi.

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
├─ scripts/     # gen-secrets, bootstrap-gateway-keys, ingest, set-password, smoke, leak-grep, backup, e2e-*
├─ docs/        # SOLUTION, ROADMAP, design/, adr/, research/
├─ docker-compose.yml, Dockerfile, Makefile, pyproject.toml (uv workspace)
```

## Tài liệu

- [`docs/design/contracts.md`](docs/design/contracts.md) — hợp đồng dùng chung, quy tắc Ports & Adapters (§9)
- [`docs/design/approval.md`](docs/design/approval.md), [`docs/design/rag-citations.md`](docs/design/rag-citations.md)
- [`docs/SOLUTION.md`](docs/SOLUTION.md), [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/adr/`](docs/adr/), [`docs/research/`](docs/research/)
- [`infra/README.md`](infra/README.md), [`data/README.md`](data/README.md), [`eval/README.md`](eval/README.md), [`web/README.md`](web/README.md)
