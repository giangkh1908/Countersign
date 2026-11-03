#!/usr/bin/env bash
# scripts/set-password.sh — đặt mật khẩu đăng nhập web cho một user thử nghiệm trong realm `acme`.
# User seed (an.nguyen, hoa.ngo, ...) không có mật khẩu sẵn; script dùng kcadm.sh trong container
# keycloak với tài khoản admin (secrets/kc_admin_password, không in ra).
#
# Dùng: bash scripts/set-password.sh <username> <mật-khẩu>
#   ví dụ: bash scripts/set-password.sh hoa.ngo Test@12345
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -eq 2 ] || { echo "dùng: bash scripts/set-password.sh <username> <mật-khẩu>" >&2; exit 2; }
docker compose exec -T keycloak bash -c '
  set -e
  kc=/opt/keycloak/bin/kcadm.sh
  $kc config credentials --server http://localhost:8080 --realm master --user admin \
      --password "$(cat /run/secrets/kc_admin_password)" --config /tmp/kcadm.config >/dev/null
  $kc set-password -r acme --username "$1" --new-password "$2" --config /tmp/kcadm.config
  rm -f /tmp/kcadm.config' _ "$1" "$2"
echo "OK: $1 đăng nhập được tại http://localhost:8300"
