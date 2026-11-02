#!/usr/bin/env bash
# scripts/e2e-leak-check.sh — kiểm rò rỉ tài liệu trái quyền (R3) cho 16 user mẫu trên stack compose thật.
# Dùng: bash scripts/e2e-leak-check.sh [--users an.nguyen,hoa.ngo] [--agent-q 4]
# Báo cáo JSON: eval/results/leak-check-<ts>.json (gitignored). Exit 1 nếu có rò rỉ.
# Tác dụng phụ (dev): tạo/xoá client Keycloak e2e-test, đặt lại mật khẩu các user được kiểm, ghi taint/tool_audit.
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose ps -q bff >/dev/null || { echo "stack chưa chạy" >&2; exit 2; }
exec uv run --all-packages python eval/e2e/leak_check.py "$@"
