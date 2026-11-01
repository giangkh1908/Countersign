#!/usr/bin/env bash
# Nạp seed ACME vào Postgres đang chạy trong compose (idempotent: ON CONFLICT DO UPDATE).
# Dùng: bash data/load_seed.sh [thư mục seed, mặc định data/generated]
# Cần: `uv run python -m data.generator` đã chạy trước. Chạy bằng superuser `postgres` trong container
# (peer/trust cục bộ), nên bỏ qua RLS ở bước nạp - đúng ý nghĩa của seed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
SEED_DIR="${1:-data/generated}"
COMPOSE="${COMPOSE:-docker compose}"

for pair in gateway:gateway knowledge:knowledge tickets:tickets; do
  db="${pair%%:*}"; f="$SEED_DIR/sql/${pair##*:}.sql"
  [ -f "$f" ] || { echo "thiếu $f - chạy: uv run python -m data.generator" >&2; exit 1; }
  echo ">> $db <- $f"
  $COMPOSE exec -T -u postgres postgres psql -v ON_ERROR_STOP=1 -q -U postgres -d "$db" < "$f"
done
echo "OK"
