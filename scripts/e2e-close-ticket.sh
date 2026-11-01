#!/usr/bin/env bash
# scripts/e2e-close-ticket.sh — E2E "đóng ticket" trên stack compose thật (không trình duyệt).
# Cần: stack đang chạy (docker compose up -d), seed đã nạp, secrets/ có agent_gateway_key.
# Dùng: bash scripts/e2e-close-ticket.sh [--skip-expiry] [--user an.nguyen] [--other-user binh.tran]
# Tác dụng phụ (dev): tạo client Keycloak `e2e-test`, đặt lại mật khẩu 2 user test, đóng 1 ticket seed.
# Nên backup trước:  docker compose exec -T -u postgres postgres pg_dumpall -U postgres > backups/<ts>/pg_dumpall.sql
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose ps -q bff >/dev/null || { echo "stack chưa chạy" >&2; exit 2; }
exec uv run --all-packages python eval/e2e/close_ticket.py "$@"
