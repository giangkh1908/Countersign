#!/bin/bash
# Spike C wrapper. Chay tu bat ky dau: bash spikes/c_agent_downstream_exchange/run.sh
# Sinh mat khau/secret ngau nhien -> setup Keycloak -> run_cases -> (trap) cleanup + status.
cd "$(dirname "$0")/../.." || exit 1
S=spikes/c_agent_downstream_exchange
export SPIKE_C_PW=$(openssl rand -hex 12) SPIKE_C_SECRET=$(openssl rand -hex 16)
kc() { MSYS_NO_PATHCONV=1 docker compose exec -T -e SPIKE_C_PW -e SPIKE_C_SECRET keycloak bash -s "$1" < $S/kc_setup.sh; }
OUT=$S/output.txt
cleanup() {
  { echo; echo "======== CLEANUP ========"; kc cleanup; echo "======== STATUS SAU CLEANUP ========"; kc status; } 2>&1 | tee -a $OUT
}
trap cleanup EXIT
{
  echo "======== STATUS TRUOC (baseline) ========"; kc status
  echo "======== SETUP ========"; kc setup || exit 1
} 2>&1 | tee $OUT
[ "${PIPESTATUS[0]}" = 0 ] || exit 1
uv run --no-project --with fastmcp==4.1.4 --with "pyjwt[crypto]" --with httpx --with uvicorn --with starlette \
  python -u $S/run_cases.py 2>&1 | tee -a $OUT
RC=${PIPESTATUS[0]}
exit $RC
