# infra — hạ tầng Docker

Nguồn: `docs/design/04-infra-data-eval.md` PHẦN A, `00-contracts.md` §1/§7. File gốc: `Dockerfile` (đa tầng, `target` theo service),
`docker-compose.yml`, `docker-compose.bench.yml`, `.env.example`, `models.lock`.

## Sơ đồ mạng

```
 trình duyệt ──► edge ──────────────────────────────────────────────────────┐
   :8300 bff   :8080 keycloak  :3000 grafana  :9090 prometheus(dev)         │
                  │                                                         │
                core (internal: true, không ra Internet) ◄──────────────────┘
   bff  agent  docs-mcp  tickets-mcp  analytics-mcp  approval-signer  policy-sidecar
   postgres  redis-state  redis-cache  keycloak(alias)  prometheus  grafana  mock-provider  migrate  seed
                  │
   gateway ◄── core ──► egress ──► api.anthropic.com / generativelanguage.googleapis.com  (CHỈ gateway có egress)
   :8000 (dev)
```

| Mạng | Thành viên | Ghi chú |
|---|---|---|
| `edge` | bff, keycloak, grafana, prometheus | thứ người dùng truy cập; Docker chỉ publish cổng của container nằm ở mạng không `internal` |
| `core` | tất cả service | `internal: true` |
| `egress` | gateway | đường duy nhất ra Internet |

## Profile

| Profile | Nội dung |
|---|---|
| (mặc định) | postgres, redis-state, redis-cache, keycloak, migrate, gateway, policy-sidecar, approval-signer, docs/tickets/analytics-mcp, agent, bff, prometheus, grafana |
| `bench` | `mock-provider`; kèm overlay `docker-compose.bench.yml` (gỡ egress của gateway, `GW_PROVIDER_OVERRIDE=mock`, ghim `cpuset`) |
| `seed` | job `seed` (sinh dữ liệu mẫu) |
| `eval` | chưa có service riêng; chỉ khi đặt `ACME_ENV=eval` mới cho adapter `permissive` (TODO M5) |
| `obs` | Langfuse v3, **chưa có file** (TODO M5: `infra/langfuse/`, nặng ~3-4 GB RAM) |

## Chạy dev

1. Docker Engine/Compose >= 2.24, RAM >= 16 GB (Windows: Docker Desktop + WSL2).
2. Thêm vào file hosts (`C:\Windows\System32\drivers\etc\hosts` hoặc `/etc/hosts`):
   `127.0.0.1 keycloak.acme.local` (browser và container cùng thấy issuer `http://keycloak.acme.local:8080/realms/acme`).
3. `bash infra/scripts/gen-secrets.sh` — sinh `./secrets/*` và `./.env` (đã gitignore). Điền `secrets/anthropic_api_key` / `gemini_api_key` nếu dùng provider thật.
   `--ci` ghi đè tất cả không hỏi (dùng cho CI compose-config); `--rotate <tên>` sinh lại một secret.
4. `make models` (tải model theo `models.lock`, sau khi điền revision/sha256 thật) — sidecar từ chối khởi động nếu thiếu/lệch.
5. `docker compose up -d --build` (cần `uv.lock` và `web/pnpm-lock.yaml` có thật).
6. Bench: `docker compose -f docker-compose.yml -f docker-compose.bench.yml --profile bench up -d gateway mock-provider`.
   Seed: `docker compose --profile seed run --rm seed`. Backup: `bash infra/scripts/backup.sh`.

Kiểm cấu hình không cần build: `bash infra/scripts/gen-secrets.sh --ci && docker compose config -q`.

## Cấu trúc

- `postgres/` — `init/00-roles-and-databases.sh` + `init/sql/*.sql` (thư mục con để entrypoint không tự chạy SQL cần biến), `pg_hba.conf`.
- `redis/` — conf hai instance, ACL template (hash SHA256 render bởi `entrypoint.sh`).
- `keycloak/` — realm `acme` (xem `keycloak/README.md`).
- `prometheus/`, `grafana/` — scrape + provisioning (dashboard JSON: `grafana/dashboards/`, TODO M5).
- `scripts/` — `gen-secrets.sh`, `backup.sh`.

## Giới hạn / lệch so với docs

- Digest `@sha256:<pin>` thay bằng tag + `TODO(M7): pin digest`. Dockerfile ở gốc repo (docs ghi `infra/docker/Dockerfile`).
- File secret mặc định mode 644 (container non-root cần đọc bind-mount); chỉ dev.
- Dev không TLS nội bộ (contracts §1).
- Chưa kiểm chạy thật (`docker compose up`) vì thiếu image build; mới kiểm `docker compose config`.
