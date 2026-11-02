#!/usr/bin/env bash
# scripts/e2e-create-ticket.sh — E2E tạo ticket (prepare -> thẻ duyệt -> signer -> resume) trên stack compose thật.
# Cần: stack chạy profile tickets, seed đã nạp, secrets/ có sẵn (hoặc đặt SECRETS_DIR).
# Dùng: bash scripts/e2e-create-ticket.sh [--keep-client]
# Tác dụng phụ (dev): tạo/xoá client Keycloak `e2e-test`, đặt lại mật khẩu 5 user test, THÊM 2 ticket thật (nhãn E2ECT-<run_id>).
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose ps -q bff >/dev/null || { echo "stack chưa chạy" >&2; exit 2; }
exec uv run --all-packages python eval/e2e/create_ticket.py "$@"
