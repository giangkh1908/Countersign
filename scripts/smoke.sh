#!/usr/bin/env bash
# scripts/smoke.sh — kiểm các service lõi đã lên và khoẻ sau `docker compose up -d --build`.
# Thoát khác 0 nếu có service nào hỏng. Dùng: bash scripts/smoke.sh
set -euo pipefail

cd "$(dirname "$0")/.."
SERVICES=(postgres redis-state keycloak mock-provider gateway docs-mcp agent bff)
INTERNAL=(agent:8200 docs-mcp:8101 mock-provider:8900)
# Profile `tickets` (R0): chỉ kiểm tickets-mcp / approval-signer khi chúng đang chạy.
if [ -n "$(docker compose ps -a -q tickets-mcp 2>/dev/null | head -n1)" ]; then
  SERVICES+=(approval-signer tickets-mcp)
  INTERNAL+=(approval-signer:8310 tickets-mcp:8102)
  echo "(profile tickets đang bật: kiểm thêm approval-signer, tickets-mcp)"
fi
fail=0
ok()  { printf '  OK    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*" >&2; fail=1; }

echo "== Docker health (healthcheck trong compose) =="
for svc in "${SERVICES[@]}"; do
  cid="$(docker compose ps -a -q "$svc" 2>/dev/null | head -n1 || true)"
  if [ -z "$cid" ]; then bad "$svc: không có container"; continue; fi
  status="$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  if [ "$status" = "running/healthy" ]; then ok "$svc ($status)"; else bad "$svc ($status)"; fi
done

echo "== Job migrate =="
for job in migrate knowledge-migrate; do
  cid="$(docker compose ps -a -q "$job" | head -n1 || true)"
  if [ -n "$cid" ] && [ "$(docker inspect -f '{{.State.Status}}/{{.State.ExitCode}}' "$cid")" = "exited/0" ]; then
    ok "$job (exited/0)"; else bad "$job chưa hoàn tất thành công"; fi
done

echo "== HTTP từ host (cổng đã publish) =="
http_ok() { # name url
  local code
  code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$2" || true)"
  if [ "$code" = "200" ]; then ok "$1 $2 -> 200"; else bad "$1 $2 -> ${code:-000}"; fi
}
http_ok gateway  http://localhost:8000/healthz
http_ok bff      http://localhost:8300/healthz
http_ok keycloak http://localhost:8080/realms/acme/.well-known/openid-configuration

echo "== HTTP nội bộ (từ container bff, mạng core) =="
for t in "${INTERNAL[@]}"; do
  if docker compose exec -T bff python -c "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://$t/healthz',timeout=3).status==200 else 1)" >/dev/null 2>&1; then
    ok "$t/healthz -> 200"; else bad "$t/healthz không phản hồi 200"; fi
done

echo "== Gateway: gọi chat có xác thực + usage_events (tuỳ chọn, cần secrets/agent_gateway_key) =="
if [ ! -s secrets/agent_gateway_key ]; then
  echo "  WARN  secrets/agent_gateway_key rỗng: bỏ qua (chạy: bash scripts/bootstrap-gateway-keys.sh --restart)"
else
  hdr="$(mktemp)"
  code="$(curl -s -o /dev/null -D "$hdr" -m 15 -w '%{http_code}' http://localhost:8000/v1/chat/completions     -H "Authorization: Bearer $(tr -d '
' < secrets/agent_gateway_key)" -H 'Content-Type: application/json'     -d '{"model":"acme-fast","messages":[{"role":"user","content":"ping"}]}' || true)"
  rid="$(tr -d '' < "$hdr" | awk -F': ' 'tolower($1)=="x-acme-request-id"{print $2}' | head -n1)"
  rm -f "$hdr"
  if [ "$code" = "200" ]; then ok "gateway /v1/chat/completions (agent key, acme-fast -> mock) -> 200"
  else bad "gateway /v1/chat/completions với agent key -> ${code:-000} (mong đợi 200)"; fi
  if [ "$code" = "200" ]; then
    if ! printf '%s' "$rid" | grep -Eq '^[0-9a-fA-F-]{36}$'; then
      bad "gateway không trả header x-acme-request-id hợp lệ"
    else
      # sink đẩy batch định kỳ (GW_SINK_FLUSH_INTERVAL_S, mặc định 2s) nên chờ tối đa ~15s
      found=0
      for _ in $(seq 1 15); do
        n="$(docker compose exec -T -u postgres postgres psql -U postgres -d gateway -tA           -c "SELECT count(*) FROM usage_events WHERE request_id = '$rid' AND status_code = 200" 2>/dev/null | tr -d '[:space:]' || true)"
        if [ "${n:-0}" = "1" ]; then found=1; break; fi
        sleep 1
      done
      if [ "$found" = "1" ]; then ok "usage_events có dòng cho request_id $rid"
      else bad "usage_events KHÔNG có dòng cho request_id $rid (kiểm EVENT_SINK_ADAPTER=postgres của gateway)"; fi
    fi
  fi
fi

if [ "$fail" -ne 0 ]; then echo "SMOKE: THẤT BẠI" >&2; exit 1; fi
echo "SMOKE: OK"
