#!/usr/bin/env bash
# infra/postgres/migrate.sh — runner migration cho DB `knowledge` (rag-citations §2.3).
#
#   migrate.sh up           áp mọi migration chưa áp, theo thứ tự tên file
#   migrate.sh down [N]     hoàn tác N migration áp gần nhất (mặc định 1)
#
# Mỗi migration chạy trong MỘT transaction cùng việc ghi/xoá dòng ở schema_migrations; chạy lại là no-op.
# Kết nối bằng role kn_owner qua biến PG* chuẩn của libpq:
#   PGHOST (mặc định postgres), PGPORT, PGDATABASE (mặc định knowledge), PGUSER (mặc định kn_owner),
#   mật khẩu từ KN_OWNER_PASSWORD_FILE (hoặc PGPASSWORD có sẵn).
# Tham số:
#   EMBED_DIM              số chiều embedding đích cho 0002 (mặc định 1024)
#   MIGRATE_FORCE_REEMBED  =1 cho phép 0002 TRUNCATE chunks khi đổi chiều (mặc định 0 => dừng)
#   MIGRATIONS_DIR         mặc định <thư mục script>/migrations/knowledge
# Dùng psql -v thay envsubst (image postgres không có envsubst).
set -euo pipefail

DIR="${MIGRATIONS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/migrations/knowledge}"
export PGHOST="${PGHOST:-postgres}"
export PGDATABASE="${PGDATABASE:-knowledge}"
export PGUSER="${PGUSER:-kn_owner}"
if [ -n "${KN_OWNER_PASSWORD_FILE:-}" ]; then PGPASSWORD="$(cat "$KN_OWNER_PASSWORD_FILE")"; export PGPASSWORD; fi

EMBED_DIM="${EMBED_DIM:-1024}"
FORCE="${MIGRATE_FORCE_REEMBED:-0}"
[[ "$EMBED_DIM" =~ ^[0-9]+$ ]] && [ "$EMBED_DIM" -ge 1 ] && [ "$EMBED_DIM" -le 16000 ] || { echo "EMBED_DIM không hợp lệ: '$EMBED_DIM'" >&2; exit 2; }
[ "$FORCE" = "0" ] || [ "$FORCE" = "1" ] || { echo "MIGRATE_FORCE_REEMBED phải là 0 hoặc 1" >&2; exit 2; }

LOCK_KEY=7301001   # khoá advisory: hai runner song song không chen nhau
sql() { psql -X -q -t -A -v ON_ERROR_STOP=1 "$@"; }

ensure_table() {
  sql -c "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
          REVOKE ALL ON schema_migrations FROM PUBLIC, kn_app, kn_ingest, mcp_audit_w;"
}

applied() { sql -c "SELECT version FROM schema_migrations ORDER BY version"; }

# run_one <up|down> <version>
run_one() {
  local dir="$1" ver="$2" file="$DIR/$2.$1.sql" bookkeeping
  [ -f "$file" ] || { echo "Thiếu file $file" >&2; exit 1; }
  if [ "$dir" = up ]; then bookkeeping="INSERT INTO schema_migrations (version) VALUES ('$ver') ON CONFLICT DO NOTHING"
  else bookkeeping="DELETE FROM schema_migrations WHERE version = '$ver'"; fi
  echo "migrate $dir $ver"
  sql -1 -v "embed_dim=$EMBED_DIM" -v "force_reembed=$FORCE" \
    -c "SELECT pg_advisory_xact_lock($LOCK_KEY)" -f "$file" -c "$bookkeeping" >/dev/null
}

cmd="${1:-}"
case "$cmd" in
  up)
    ensure_table
    done_list="$(applied)"
    for f in "$DIR"/*.up.sql; do
      ver="$(basename "$f" .up.sql)"
      [[ "$ver" =~ ^[0-9]{4}_[a-z0-9_]+$ ]] || { echo "Tên migration lạ: $ver" >&2; exit 1; }
      if grep -qx "$ver" <<<"$done_list"; then continue; fi
      run_one up "$ver"
    done
    # 0002 đã áp thì vòng trên bỏ qua, nên đổi EMBED_DIM về sau phải chạy lại nó (idempotent, có chặn dữ liệu).
    cur_dim="$(sql -c "SELECT value FROM index_meta WHERE key = 'embed_dim'")"
    if [ "$cur_dim" != "$EMBED_DIM" ]; then
      echo "đổi số chiều embedding: $cur_dim -> $EMBED_DIM"
      run_one up 0002_embedding_dim
    fi
    echo "migrate up xong"
    ;;
  down)
    n="${2:-1}"
    [[ "$n" =~ ^[0-9]+$ ]] || { echo "N phải là số nguyên" >&2; exit 2; }
    ensure_table
    # sql -t -A: mỗi version một dòng; lấy N bản mới nhất
    mapfile -t todo < <(sql -c "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT $n")
    for ver in "${todo[@]}"; do
      [ -n "$ver" ] && run_one down "$ver"
    done
    echo "migrate down xong (${#todo[@]} migration)"
    ;;
  *)
    echo "Dùng: migrate.sh up | migrate.sh down [N]" >&2
    exit 2
    ;;
esac
