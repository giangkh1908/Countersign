# infra — hạ tầng Docker

Dịch vụ, cổng, mạng và profile: xem [`docs/design/contracts.md`](../docs/design/contracts.md) §1. File gốc: `Dockerfile` (đa tầng, `target` theo service), `docker-compose.yml`, `.env.example`.

Mạng: `edge` (bff, keycloak, grafana, prometheus), `core` (`internal: true`, mọi service), `egress` (chỉ gateway có đường ra Internet).

## Chạy dev

1. Docker Compose >= 2.24. Thêm `127.0.0.1 keycloak.acme.local` vào file hosts (`C:\Windows\System32\drivers\etc\hosts` hoặc `/etc/hosts`).
2. `bash scripts/gen-secrets.sh` — sinh `./secrets/*` và `./.env` (gitignore). `--ci` ghi đè không hỏi; `--rotate <tên>` sinh lại một secret.
3. `docker compose up -d --build --wait`, rồi seed và bootstrap key theo thứ tự trong [README gốc](../README.md).

Kiểm cấu hình không cần build: `bash scripts/gen-secrets.sh --ci && docker compose config -q`.
Backup: `bash scripts/backup.sh`. Kiểm RLS trên DB thật: `bash infra/postgres/verify/run.sh`.

## Cấu trúc

- `postgres/` — `init/00-roles-and-databases.sh` và `init/sql/*.sql` (chỉ chạy trên volume trống; đổi schema thì `docker compose down -v`), `pg_hba.conf`, `verify/`.
- `redis/` — cấu hình và ACL của `redis-state` (hash SHA256 render bởi `entrypoint.sh`).
- `keycloak/` — realm `acme` ([README](keycloak/README.md)).
- `prometheus/`, `grafana/` — scrape và provisioning (profile `obs`).

## Giới hạn

- Image dùng tag, chưa pin digest.
- File secret mặc định mode 644 (container non-root cần đọc bind-mount); chỉ dev.
- Dev không TLS nội bộ.
