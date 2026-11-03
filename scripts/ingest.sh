#!/usr/bin/env bash
# scripts/ingest.sh — nạp tài liệu vào kho tri thức (docs-mcp) từ bên trong mạng Docker.
# Postgres không publish cổng ra host, nên ingest chạy trong một container tạm dựng từ image docs-mcp:
# dữ liệu `data/` mount chỉ đọc, URL role `kn_ingest` dựng từ secrets/kn_ingest_password ngay trong
# container (không in, không ghi ra đĩa). Embedding đi qua gateway (alias acme-embed).
#
# Dùng (stack phải đang chạy):
#   bash scripts/ingest.sh                         # mặc định: data/raw/vbpl (luật) + data/generated (tài liệu ACME)
#   bash scripts/ingest.sh data/corpus --force     # thư mục khác; tham số sau thư mục chuyển cho mcp_docs.ingest
# Idempotent: tài liệu không đổi (nội dung, ACL, model embedding) thì bỏ qua.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -W 2>/dev/null || pwd)   # Git Bash cần đường dẫn Windows cho bind mount
export MSYS_NO_PATHCONV=1

RUN='import os, runpy, sys
pw = open("/run/secrets/kn_ingest_password", encoding="utf8").read().strip()
os.environ["DOCS_INGEST_DATABASE_URL"] = f"postgresql://kn_ingest:{pw}@postgres:5432/knowledge"
sys.argv = ["mcp_docs.ingest", *sys.argv[1:]]
runpy.run_module("mcp_docs.ingest", run_name="__main__")'

ingest() {
  local dir=$1; shift
  if [ ! -d "$dir" ]; then
    echo "bỏ qua $dir: chưa có thư mục (xem README mục Chạy lần đầu)" >&2
    return 0
  fi
  echo "== ingest $dir"
  docker compose run --rm --no-deps -T \
    -v "$ROOT/data:/app/data:ro" \
    -v "$ROOT/secrets/kn_ingest_password:/run/secrets/kn_ingest_password:ro" \
    docs-mcp python -c "$RUN" --corpus-dir "$dir" "$@" 2>&1 | grep -E "ingest OK|ERROR|Error|rror:" || true
}

if [ $# -eq 0 ]; then
  ingest data/raw/vbpl
  ingest data/generated
else
  dir=$1; shift
  ingest "$dir" "$@"
fi
# docs-mcp kiểm model embedding của chỉ mục lúc khởi động: restart để đọc lại sau khi nạp.
docker compose restart docs-mcp >/dev/null && docker compose up -d --wait docs-mcp >/dev/null && echo "docs-mcp đã nạp lại chỉ mục"
