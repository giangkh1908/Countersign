#!/usr/bin/env bash
# scripts/bootstrap-gateway-keys.sh
# Tạo API key gateway cho agent-service và docs-mcp bằng `gateway.cli create-key`,
# ghi vào secrets/agent_gateway_key và secrets/docs_gateway_key (cùng file mode với gen-secrets.sh).
#
# Dùng:
#   bash scripts/bootstrap-gateway-keys.sh            # idempotent: key hợp lệ có sẵn giữ nguyên, chỉ đặt lại danh sách model
#   bash scripts/bootstrap-gateway-keys.sh --rotate   # tạo key mới cho cả hai (key cũ KHÔNG tự thu hồi;
#                                                           # thu hồi bằng `gateway.cli revoke-key`)
#
# Cần: stack compose đang chạy (gateway healthy; bảng api_keys/departments đã có; seed phòng ban IT đã nạp).
# Không bao giờ in key ra stdout/log. Sau khi tạo: docker compose restart agent docs-mcp (hoặc --restart:
# restart rồi chờ agent + docs-mcp healthy mới thoát, chờ thất bại thì exit khác 0).
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
    # Kiểm key trong file còn dùng được trong DB (DB mới sau `down -v` thì file cũ vô nghĩa).
    # Key đi qua stdin, không qua argv/env; check-key không in gì ra khỏi container.
    local rc=0
    $COMPOSE exec -T gateway python -m gateway.cli check-key < "$file" >/dev/null 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
      # Key cấp trước khi danh sách model đổi: đặt lại model tại chỗ, không phải rotate.
      if $COMPOSE exec -T gateway python -m gateway.cli --actor bootstrap-gateway-keys \
           update-key-models --allowed-models "$models" < "$file" >/dev/null 2>&1; then
        echo "skip   $name: $fname đã có key hợp lệ (models=$models; dùng --rotate để tạo lại)"
        return 0
      fi
      echo "FAIL   $name: không cập nhật được danh sách model của key trong secrets/$fname (xem: $COMPOSE logs gateway)" >&2
      return 1
    elif [ "$rc" -eq 3 ]; then
      echo "key trong secrets/$fname không có trong DB (DB mới?), tạo key mới"
    else
      echo "FAIL   $name: không kiểm được key trong secrets/$fname (rc=$rc; xem: $COMPOSE logs gateway)" >&2
      return 1
    fi
  fi
  local key
  # stdout = plaintext key (chỉ giữ trong biến); stderr (key_id) bỏ đi để log sạch.
  key="$($COMPOSE exec -T gateway python -m gateway.cli --actor bootstrap-gateway-keys create-key \
        --name "$name" --dept "$DEPT" --owner-type service --owner-ref "$owner" \
        --allowed-models "$models" "$@" 2>/dev/null | tr -d '\r\n')" || key=""  # lỗi thì rơi xuống nhánh FAIL, không thoát im lặng vì set -e
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

# agent-service: gọi LLM thay mặt người dùng, nên tin end-user token. `acme-judge` cho bộ kiểm chứng
# trích dẫn (R2). Key cấp trước R2 không có alias này: script đặt lại danh sách model của key còn hợp lệ.
provision agent_gateway_key agent agent-service acme-fast,acme-smart,acme-judge \
  --rpm 120 --tpm 200000 --max-concurrency 8 --trust-end-user-token
# docs-mcp: embedding và rerank. `create-key` không kiểm alias với catalog, nên key cấp được dù gateway
# chưa phục vụ `acme-rerank` (chỉ có trong models.ollama.yaml). Key hợp lệ có sẵn được đặt lại danh sách
# model bằng `update-key-models` (không rotate).
provision docs_gateway_key docs-mcp docs-mcp acme-embed,acme-rerank \
  --rpm 120 --tpm 200000 --max-concurrency 4

if [ "$created" -eq 1 ] && [ "$RESTART" -eq 1 ]; then
  $COMPOSE restart agent docs-mcp
  # restart thoát ngay khi service còn `starting`; chờ healthy để bước kế tiếp (smoke.sh) không FAIL giả.
  # `up -d --wait` trả exit khác 0 nếu chờ thất bại; set -e làm script thoát theo.
  $COMPOSE up -d --wait agent docs-mcp
fi
echo "bootstrap-gateway-keys: xong."
