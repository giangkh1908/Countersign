#!/usr/bin/env bash
# scripts/e2e-notify.sh — E2E notify-mcp (gửi báo cáo vào nhóm chat) trên stack compose thật.
# Cần: stack đang chạy với profile tickets + notify (docker compose --profile tickets --profile notify up -d),
# seed đã nạp, secrets/ có agent_gateway_key. Kênh `fake` nên không gửi gì ra ngoài.
# Dùng: bash scripts/e2e-notify.sh [--keep-client]
# Tác dụng phụ (dev): tạo/xoá client Keycloak `e2e-test`, đặt lại mật khẩu 5 user test, thêm 1 dòng report_deliveries.
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose ps -q bff >/dev/null || { echo "stack chưa chạy" >&2; exit 2; }
[ -n "$(docker compose ps -q notify-mcp)" ] || { echo "notify-mcp chưa chạy (cần profile notify)" >&2; exit 2; }
exec uv run --all-packages python eval/e2e/notify.py "$@"
