#!/usr/bin/env bash
# scripts/bootstrap-gateway-keys.sh
# Tạo API key gateway cho agent-service và docs-mcp bằng `gateway.cli create-key`,
# ghi vào secrets/agent_gateway_key và secrets/docs_gateway_key (cùng file mode với gen-secrets.sh).
#
# Dùng:
#   bash scripts/bootstrap-gateway-keys.sh            # idempotent: bỏ qua key mà file đã khác rỗng
#   bash scripts/bootstrap-gateway-keys.sh --rotate   # tạo key mới cho cả hai (key cũ KHÔNG tự thu hồi;
#                                                           # thu hồi bằng `gateway.cli revoke-key`)
#
# Cần: stack compose đang chạy (gateway healthy; bảng api_keys/departments đã có; seed phòng ban IT đã nạp).
# Không bao giờ in key ra stdout/log. Sau khi tạo: docker compose restart agent docs-mcp (hoặc --restart).
# Biến môi trường: SECRETS_MODE (mặc định 644, như gen-secrets.sh), GW_KEYS_DEPT (mặc định IT).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SEC="$ROOT/secrets"
MODE="${SECRETS_MODE:-644}"
DEPT="${GW_KEYS_DEPT:-IT}"
COMPOSE="${COMPOSE:-docker compose}"
ROTATE=0
RESTART=0
while [ $# -gt 0 ]; do
  case "$1" in
    --rotate) ROTATE=1 ;;
    --restart) RESTART=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Tham số lạ: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"
created=0

# provision FILE_NAME NAME OWNER_REF ALLOWED_MODELS [extra create-key args...]
provision() {
  local fname="$1" file="$SEC/$1" name="$2" owner="$3" models="$4"; shift 4
  if [ -s "$file" ] && [ "$ROTATE" -eq 0 ]; then
    echo "skip   $name: $fname đã có key (dùng --rotate để tạo lại)"
    return 0
  fi
  local key
  # stdout = plaintext key (chỉ giữ trong biến); stderr (key_id) bỏ đi để log sạch.
  key="$($COMPOSE exec -T gateway python -m gateway.cli --actor bootstrap-gateway-keys create-key \
        --name "$name" --dept "$DEPT" --owner-type service --owner-ref "$owner" \
        --allowed-models "$models" "$@" 2>/dev/null | tr -d '\r\n')"
  if [ -z "$key" ]; then
    echo "FAIL   $name: gateway.cli create-key không trả key (xem: $COMPOSE logs gateway; kiểm tra bảng/phòng ban $DEPT)" >&2
    return 1
  fi
  printf '%s' "$key" > "$file"
  chmod "$MODE" "$file"
  key=""
  echo "create $name -> secrets/$fname (dept=$DEPT, models=$models)"
  created=1
}

# agent-service: gọi LLM thay mặt người dùng, nên tin end-user token.
provision agent_gateway_key agent agent-service acme-fast,acme-smart \
  --rpm 120 --tpm 200000 --max-concurrency 8 --trust-end-user-token
# docs-mcp: chỉ embedding. `create-key` không kiểm alias với catalog, nên key cấp được dù gateway
# chưa phục vụ `acme-embed`; khi R1 thêm alias vào models.yaml là dùng được ngay, không phải cấp lại key.
provision docs_gateway_key docs-mcp docs-mcp acme-embed \
  --rpm 120 --tpm 200000 --max-concurrency 4

if [ "$created" -eq 1 ] && [ "$RESTART" -eq 1 ]; then
  $COMPOSE restart agent docs-mcp
fi
echo "bootstrap-gateway-keys: xong."
