#!/usr/bin/env bash
# infra/scripts/gen-secrets.sh  (docs/design/04 §5.1)
# Sinh ./secrets/* (gitignore) và ./.env (từ .env.example nếu chưa có).
#
# Dùng:
#   bash infra/scripts/gen-secrets.sh                  # chỉ tạo file CHƯA có (idempotent)
#   bash infra/scripts/gen-secrets.sh --rotate NAME    # sinh lại 1 secret (vd redis_gateway_password)
#   bash infra/scripts/gen-secrets.sh --ci             # không tương tác, GHI ĐÈ tất cả, đủ cho `docker compose config`
#
# Biến môi trường: SECRETS_MODE (mặc định 644: container chạy uid 10001/999 không phải chủ
# file bind-mount; chỉ dev. Prod dùng secret manager, M7).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SEC="$ROOT/secrets"
MODE="${SECRETS_MODE:-644}"
CI=0
ROTATE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --ci) CI=1 ;;
    --rotate) shift; ROTATE="${1:?--rotate cần tên secret}" ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Tham số lạ: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$SEC/intent-keys"
chmod 755 "$SEC" "$SEC/intent-keys" 2>/dev/null || true

# tr -d '\r': openssl trên Git Bash/Windows in CRLF; ký tự CR lọt vào secret làm hỏng env/JSON (vd import realm Keycloak).
rand_pw()  { openssl rand -base64 33 | tr -d '=+/\r\n' | cut -c1-40; }
rand_b64() { openssl rand -base64 "$1" | tr -d '\r\n'; }
rand_hex() { openssl rand -hex "$1" | tr -d '\r\n'; }

# Có cần (tạo lại) secret NAME không?
should_write() {
  local f="$SEC/$1"
  [ "$CI" -eq 1 ] && return 0
  [ "$ROTATE" = "$1" ] && return 0
  [ ! -f "$f" ]
}

# put NAME GENERATOR [ARG]
put() {
  local name="$1"; shift
  should_write "$name" || return 0
  "$@" > "$SEC/$name"
  chmod "$MODE" "$SEC/$name"
}

# placeholder rỗng (không ghi đè nếu đã có, trừ --ci)
put_empty() {
  should_write "$1" || return 0
  : > "$SEC/$1"
  chmod "$MODE" "$SEC/$1"
}

for n in pg_superuser_password gw_owner_password gw_app_password kn_owner_password kn_app_password \
         kn_ingest_password tk_owner_password tk_app_password an_owner_password an_reader_password \
         ag_app_password ag_owner_password mcp_audit_password kc_app_password lf_app_password \
         gw_report_password redis_gateway_password redis_tickets_password redis_docs_password \
         redis_analytics_password redis_bff_password redis_ops_password redis_health_password \
         kc_admin_password grafana_admin_password; do
  put "$n" rand_pw
done

put gw_key_pepper          rand_b64 48
put audit_hmac_key         rand_b64 48
put sidecar_token          rand_hex 32
put metrics_token          rand_hex 32
put gw_admin_token         rand_hex 32
put agent_checkpoint_key   rand_b64 32
put bff_session_key        rand_b64 32
put kc_agent_client_secret rand_hex 24
put bff_oidc_client_secret rand_hex 24
put lf_nextauth_secret     rand_b64 32
put lf_salt                rand_b64 32

# Key cần tạo sau khi hệ thống chạy / do người dùng cấp: file rỗng làm placeholder
put_empty docs_gateway_key      # key service docs-mcp -> gateway (Admin API POST /admin/keys)
put_empty agent_gateway_key     # key của agent-service (tạo sau khi gateway chạy)
put_empty anthropic_api_key     # điền key thật nếu dùng provider thật
put_empty gemini_api_key

# URL đầy đủ cho gateway (ghi chú 1 của §1.3); mật khẩu chỉ gồm [A-Za-z0-9] nên không cần url-encode
if should_write gw_database_url || [ "$ROTATE" = "gw_app_password" ]; then
  printf 'postgresql://gw_app:%s@postgres:5432/gateway' "$(cat "$SEC/gw_app_password")" > "$SEC/gw_database_url"
  chmod "$MODE" "$SEC/gw_database_url"
fi

# Cặp khoá ES256: approval (private -> approval-signer, public -> tickets-mcp),
# intent (private -> tickets-mcp, public -> approval-signer qua secrets/intent-keys/)
genkey() {
  local priv="$SEC/${1}_es256_private.pem" pub="$SEC/${1}_es256_public.pem"
  if [ -f "$priv" ] && [ "$CI" -eq 0 ] && [ "$ROTATE" != "${1}_es256" ]; then return 0; fi
  openssl ecparam -name prime256v1 -genkey -noout -out "$priv"
  openssl ec -in "$priv" -pubout -out "$pub" 2>/dev/null
  chmod "$MODE" "$priv" "$pub"
}
genkey approval
genkey intent
cp "$SEC/intent_es256_public.pem" "$SEC/intent-keys/tickets-mcp-1.pem"
chmod "$MODE" "$SEC/intent-keys/tickets-mcp-1.pem"

# .env: tham số KHÔNG bí mật (xem .env.example)
if [ ! -f "$ROOT/.env" ] || [ "$CI" -eq 1 ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

if [ "$CI" -eq 1 ]; then
  echo "gen-secrets (--ci): đã ghi đè $SEC và .env (chỉ dùng cho kiểm tra, không dùng thật)."
else
  echo "gen-secrets: xong. Thư mục: $SEC (đã gitignore). Điền anthropic_api_key/gemini_api_key nếu cần provider thật."
fi
