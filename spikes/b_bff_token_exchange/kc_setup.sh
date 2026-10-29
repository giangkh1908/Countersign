#!/bin/bash
# Spike B - cau hinh Keycloak. Chay TRONG container keycloak:
#   docker compose exec -T [-e SPIKE_B_PW_AN=.. -e SPIKE_B_PW_BINH=..] keycloak bash -s <subcmd> < kc_setup.sh
# Subcommand: snapshot | setup | export | probe-create | probe-enable | probe-delete | cleanup
# Dung file config kcadm RIENG (/tmp/kcadm-spikeb.config) de khong de len config cua Spike C.
KC=/opt/keycloak/bin/kcadm.sh
CFG="--config /tmp/kcadm-spikeb.config"
R=acme
TMP_URI="http://localhost:8310/auth/callback"
USERS="an.nguyen binh.tran"

$KC config credentials --server http://localhost:8080 --realm master --user admin \
  --password "$(cat /run/secrets/kc_admin_password)" $CFG >/dev/null || { echo "KC login failed" >&2; exit 1; }

kc() { $KC "$@" $CFG; }
cid_of() { kc get clients -r $R -q clientId="$1" --fields id --format csv --noquotes; }
uid_of() { kc get users -r $R -q username="$1" -q exact=true --fields id --format csv --noquotes; }
# lay mang chuoi redirectUris (moi phan tu 1 dong, da bo dau nhay)
uris_of() { kc get clients/$1 -r $R --fields redirectUris | grep -o '"http[^"]*"' | tr -d '"'; }
json_array() { local first=1 out="["; while read -r l; do [ -z "$l" ] && continue; [ $first = 0 ] && out="$out,"; out="$out\"$l\""; first=0; done; echo "$out]"; }

user_state() {
  local u=$1 id; id=$(uid_of $u)
  echo "\"$u\": {\"id\": \"$id\","
  echo "\"user\": $(kc get users/$id -r $R --fields username,enabled,requiredActions,emailVerified | tr -d '\n'),"
  echo "\"credentials\": $(kc get users/$id/credentials -r $R --fields type,id,createdDate | tr -d '\n')}"
}

state() {
  local chat; chat=$(cid_of chat-ui); local sig; sig=$(cid_of approval-signer)
  echo "{"
  echo "\"chat-ui\": $(kc get clients/$chat -r $R --fields "clientId,redirectUris,attributes(*)" | tr -d '\n'),"
  echo "\"approval-signer\": $(kc get clients/$sig -r $R --fields "clientId,enabled,publicClient,bearerOnly,standardFlowEnabled,serviceAccountsEnabled,attributes(*),defaultClientScopes,optionalClientScopes" | tr -d '\n'),"
  first=1
  for u in $USERS; do [ $first = 0 ] && echo ","; first=0; user_state $u; done
  echo ","
  echo "\"spike_b_clients\": \"$(kc get clients -r $R -q clientId=spike-b-probe --fields clientId --format csv --noquotes | tr '\n' ' ')\""
  echo "}"
}

case "$1" in
snapshot) state ;;

setup)
  [ -n "$SPIKE_B_PW_AN" ] && [ -n "$SPIKE_B_PW_BINH" ] || { echo "thieu SPIKE_B_PW_AN / SPIKE_B_PW_BINH" >&2; exit 1; }
  chat=$(cid_of chat-ui)
  if uris_of $chat | grep -qx "$TMP_URI"; then echo "redirect URI tam da co"; else
    n=$(uris_of $chat | wc -l)
    # doc-sua-ghi: gan phan tu o vi tri n (them vao cuoi), giu URI cu
    kc update clients/$chat -r $R -s "redirectUris[$n]=$TMP_URI" && echo "added redirect URI $TMP_URI at index $n"
  fi
  for u in $USERS; do
    id=$(uid_of $u)
    if [ $u = an.nguyen ]; then pw=$SPIKE_B_PW_AN; else pw=$SPIKE_B_PW_BINH; fi
    kc set-password -r $R --username $u --new-password "$pw" && echo "password (non-temporary) set for $u"
    ra=$(kc get users/$id -r $R --fields requiredActions | tr -d ' \n')
    echo "requiredActions($u) = $ra"
    case "$ra" in *'[]'*) ;; *) kc update users/$id -r $R -s 'requiredActions=[]' && echo "REMOVED requiredActions of $u (was $ra)";; esac
  done ;;

export)
  for c in chat-ui agent-service; do
    id=$(cid_of $c)
    echo "== client $c =="
    kc get clients/$id -r $R --fields "clientId,attributes(*),defaultClientScopes,optionalClientScopes,redirectUris"
  done
  echo "== PARTIAL-EXPORT-BEGIN =="
  kc create "realms/$R/partial-export?exportClients=true" -r $R -s dummy=1 -o
  echo "== PARTIAL-EXPORT-END ==" ;;

probe-create)
  if [ -n "$(cid_of spike-b-probe)" ]; then id=$(cid_of spike-b-probe); else
    id=$(kc create clients -r $R -s clientId=spike-b-probe -s enabled=true -s publicClient=false \
      -s serviceAccountsEnabled=true -s standardFlowEnabled=false -s directAccessGrantsEnabled=false -i); fi
  # in secret ra stdout cho Python doc (khong ghi file)
  kc get clients/$id/client-secret -r $R | grep -o '"value" *: *"[^"]*"' | sed 's/.*: *"\(.*\)"/\1/' ;;

probe-enable)
  id=$(cid_of spike-b-probe)
  kc update clients/$id -r $R -s 'attributes."standard.token.exchange.enabled"=true' && echo enabled ;;

probe-delete)
  id=$(cid_of spike-b-probe); [ -n "$id" ] && kc delete clients/$id -r $R && echo "deleted spike-b-probe" ;;

cleanup)
  chat=$(cid_of chat-ui)
  rest=$(uris_of $chat | grep -vx "$TMP_URI" | json_array)
  kc update clients/$chat -r $R -s "redirectUris=$rest" && echo "redirectUris restored -> $rest"
  for u in $USERS; do
    id=$(uid_of $u)
    for cid in $(kc get users/$id/credentials -r $R --fields id,type --format csv --noquotes | grep -i password | cut -d, -f1); do
      kc delete users/$id/credentials/$cid -r $R && echo "deleted password credential of $u (khong khoi phuc duoc mat khau cu neu truoc do co)"
    done
    kc delete attack-detection/brute-force/users/$id -r $R 2>/dev/null && echo "cleared brute-force lockout of $u"
  done
  for id in $(kc get clients -r $R --fields id,clientId --format csv --noquotes | grep ',spike-b-' | cut -d, -f1); do
    kc delete clients/$id -r $R && echo "deleted spike-b client $id"
  done
  echo "== STATE AFTER CLEANUP =="; state ;;
*) echo "unknown subcmd" >&2; exit 2 ;;
esac
