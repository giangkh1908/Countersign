#!/usr/bin/env bash
# Leak-grep (docs/design/00-contracts.md §9.1 mục 8). Exit 1 nếu có kết quả.
# Thư mục chưa tồn tại được coi là pass.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail=0
report() { # $1 = tên kiểm tra, $2 = output
  if [ -n "$2" ]; then
    echo "$2"
    echo "::error::leak-grep: $1"
    fail=1
  fi
}

# 1. Vendor không được lọt vào business logic
src_dirs=()
for d in packages/*/src; do
  if [ -d "$d" ]; then src_dirs+=("$d"); fi
done
if [ "${#src_dirs[@]}" -gt 0 ]; then
  out=$(grep -rniE "anthropic|gemini|google|keycloak|presidio|underthesea|pgvector|qdrant|fastmcp|langfuse" \
          "${src_dirs[@]}" --include=*.py | grep -vE "/adapters/|factory\.py|settings\.py" || true)
  report "vendor name leaked outside adapters/factory/settings" "$out"
fi

# 2. Gateway không nạp model nặng (D2)
if [ -d packages/gateway/src ]; then
  out=$(grep -rniE "onnxruntime|torch|tokenizers|transformers|sentence_transformers|huggingface_hub" \
          packages/gateway/src --include=*.py || true)
  report "gateway imports model runtime" "$out"
fi

# 3. Frontend (D15): chỉ src/api/client.ts được dùng fetch/SSE
if [ -d web/src ]; then
  out=$(grep -rnE "\bfetch\(|XMLHttpRequest|EventSource|fetch-event-source|axios|keycloak-js|oidc-client" \
          web/src --include=*.ts --include=*.tsx | grep -vE "src/api/client\.ts|\.test\.tsx?:" || true)
  report "fetch/vendor client outside src/api/client.ts" "$out"
fi

if [ "$fail" -ne 0 ]; then exit 1; fi
echo "leak-grep: OK"
