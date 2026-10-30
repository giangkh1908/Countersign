#!/usr/bin/env bash
# Kiểm chứng RLS/quyền trên Postgres đang chạy trong compose (cần seed đã nạp: bash data/load_seed.sh).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
COMPOSE="${COMPOSE:-docker compose}"
$COMPOSE exec -T -u postgres postgres psql -v ON_ERROR_STOP=1 -q -U postgres -d postgres < infra/postgres/verify/rls.sql
