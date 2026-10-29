#!/bin/bash
# infra/postgres/init/00-roles-and-databases.sh  (docs/design/04 §3.1)
# Chạy một lần khi pg_data còn trống (docker-entrypoint-initdb.d). Các file .sql nằm ở thư mục con
# `sql/` để entrypoint KHÔNG tự chạy chúng (chúng cần biến psql -v).
set -euo pipefail
pw() { cat "/run/secrets/$1"; }
SQL_DIR=/docker-entrypoint-initdb.d/sql

psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
  -v gw_owner_pw="$(pw gw_owner_password)"   -v gw_app_pw="$(pw gw_app_password)" \
  -v kn_owner_pw="$(pw kn_owner_password)"   -v kn_app_pw="$(pw kn_app_password)" -v kn_ingest_pw="$(pw kn_ingest_password)" \
  -v tk_owner_pw="$(pw tk_owner_password)"   -v tk_app_pw="$(pw tk_app_password)" \
  -v an_owner_pw="$(pw an_owner_password)"   -v an_reader_pw="$(pw an_reader_password)" \
  -v ag_owner_pw="$(pw ag_owner_password)"   -v mcp_audit_pw="$(pw mcp_audit_password)" \
  -v ag_app_pw="$(pw ag_app_password)"       -v kc_app_pw="$(pw kc_app_password)" \
  -v lf_app_pw="$(pw lf_app_password)"       -v gw_report_pw="$(pw gw_report_password)" \
  -f "$SQL_DIR/10-roles.sql"

for db in gateway knowledge tickets analytics agent keycloak langfuse; do
  psql -v ON_ERROR_STOP=1 -U postgres -d "$db" -f "$SQL_DIR/20-ext-and-grants.sql"
  if [ -f "$SQL_DIR/30-$db.sql" ]; then
    psql -v ON_ERROR_STOP=1 -U postgres -d "$db" -f "$SQL_DIR/30-$db.sql"
  fi
done
