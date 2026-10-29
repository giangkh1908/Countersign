# AI_EXAMPLE — Nền tảng trợ lý AI nội bộ doanh nghiệp

LangGraph điều phối agent, MCP kết nối hệ thống nghiệp vụ, LLM Gateway tự phát triển (bảo mật + kiểm soát chi phí), giao diện React + TS qua BFF.

## Cấu trúc repo

```
├─ pyproject.toml        # uv workspace root (ruff, pytest)
├─ docker-compose.yml
├─ models.lock           # model ML: revision, sha256, license
├─ infra/                # keycloak, postgres init, redis, prometheus, grafana, scripts/
├─ web/                  # SPA Vite + React + TS (pnpm)
├─ packages/             # common, gateway, policy_sidecar, approval_signer,
│                        # mcp_docs, mcp_tickets, mcp_analytics, agent, bff, mock_provider
├─ data/                 # generator ACME giả lập, corpus độc, tập test PII
├─ eval/                 # bench (k6/vegeta), promptfoo, security regression, notebooks
├─ scripts/              # leak-grep.sh
└─ docs/                 # SOLUTION, ROADMAP, design/, adr/, research/, reviews/
```

## Yêu cầu

uv, Python 3.12, Node 22, pnpm, Docker (compose v2). Trên Windows dùng Git Bash hoặc WSL cho `make` và các script `.sh`.

## Quickstart (dev)

1. Thêm vào file hosts: `127.0.0.1 keycloak.acme.local`
2. `make setup` — cài phụ thuộc Python và web
3. `make secrets` — sinh secret vào `.env` (đã gitignore)
4. `make up` — dựng stack bằng Docker Compose
5. Mở http://localhost:8300

## Kiểm thử

```
make lint        # ruff format --check + ruff check
make test        # pytest (packages/)
make test-web    # vitest
make leak-grep   # kiểm kiến trúc (contracts §9.1 mục 8)
make eval        # eval/ (chạy riêng, không nằm trong make test)
```

## Ports & Adapters (bắt buộc)

Tích hợp bên ngoài nằm sau port `abc.ABC`; mỗi vendor một file `adapters/<vendor>.py`; `factory.py` chọn vendor bằng registry dict + lazy import; retry/breaker/fallback/metrics là decorator cùng port; `services/` và `api/` chỉ import port và factory. Thêm vendor = thêm file, không sửa nghiệp vụ. Chi tiết: [`docs/design/00-contracts.md`](docs/design/00-contracts.md) §9.

## Tài liệu

- [`docs/SOLUTION.md`](docs/SOLUTION.md) — giải pháp và kiến trúc
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — milestone M0–M7
- [`docs/design/`](docs/design/) — hợp đồng, quyết định (`DECISIONS-v1.2.md`), thiết kế 01–07
- [`docs/adr/`](docs/adr/), [`docs/reviews/`](docs/reviews/), [`docs/research/`](docs/research/)
