#!/bin/bash
# Chay TRONG container keycloak: MSYS_NO_PATHCONV=1 docker compose exec -T -e SPIKE_C_PW=.. -e SPIKE_C_SECRET=.. keycloak bash -s <setup|status|cleanup> < kc_setup.sh
# Chi tao/xoa client spike-c-* va credential tam cua chi.le / tam.vu. Khong sua client/scope co san.
KC=/opt/keycloak/bin/kcadm.sh; C="--config /tmp/kcadm-spike-c.config"; R="-r acme"
MARK=/tmp/spike-c-marker
$KC config credentials --server http://localhost:8080 --realm master --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" --password "$(cat /run/secrets/kc_admin_password)" $C >/dev/null 2>&1 || exit 1

cid()  { $KC get clients $R -q clientId="$1" --fields id --format csv --noquotes $C | head -1; }
uid()  { $KC get users $R -q username="$1" -q exact=true --fields id --format csv --noquotes $C | head -1; }
scid() { $KC get client-scopes $R --fields id,name --format csv --noquotes $C | grep ",$1\$" | cut -d, -f1 | head -1; }
ncred(){ local u; u=$(uid "$1"); $KC get users/$u/credentials $R --fields id --format csv --noquotes $C | grep -c .; }

mk_client() { # name lifespan
  local name=$1 life=$2 id
  id=$(cid "$name")
  if [ -n "$id" ]; then $KC delete clients/$id $R $C; fi
  local extra=()
  [ -n "$life" ] && extra=(-s "attributes.\"access.token.lifespan\"=$life")
  $KC create clients $R $C -s clientId=$name -s enabled=true -s publicClient=false -s secret="$SPIKE_C_SECRET" \
    -s directAccessGrantsEnabled=true -s standardFlowEnabled=false -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false -s 'attributes."standard.token.exchange.enabled"=true' "${extra[@]}" >/dev/null || return 1
  id=$(cid "$name")
  $KC update clients/$id/default-client-scopes/$(scid acme-claims) $R $C
  $KC create clients/$id/protocol-mappers/models $R $C -s name=aud-self -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper -s "config.\"included.client.audience\"=$name" \
    -s 'config."access.token.claim"=true' -s 'config."id.token.claim"=false' >/dev/null
  # LIEN KET (khong sua) scope agent:invoke thanh optional scope cua client tam
  $KC update clients/$id/optional-client-scopes/$(scid agent:invoke) $R $C
  echo "created $name id=$id"
}

fingerprint() {
  for c in agent-service tickets-mcp llm-gateway; do
    id=$(cid $c)
    echo "== client $c: sha256(json)=$($KC get clients/$id $R $C | sha256sum | cut -c1-16)"
    echo "   default : $($KC get clients/$id/default-client-scopes $R --fields name --format csv --noquotes $C | sort | tr '\n' ' ')"
    echo "   optional: $($KC get clients/$id/optional-client-scopes $R --fields name --format csv --noquotes $C | sort | tr '\n' ' ')"
    echo "   mappers : $($KC get clients/$id/protocol-mappers/models $R --fields name --format csv --noquotes $C | sort | tr '\n' ' ')"
  done
  for s in llm:invoke tickets:read tickets:write agent:invoke; do
    id=$(scid $s); echo "== scope $s: sha256(json)=$($KC get client-scopes/$id $R $C | sha256sum | cut -c1-16)"
  done
}

case "$1" in
 setup)
  [ -n "$SPIKE_C_PW" ] && [ -n "$SPIKE_C_SECRET" ] || { echo "thieu SPIKE_C_PW/SPIKE_C_SECRET"; exit 2; }
  for u in chi.le tam.vu; do
    n=$(ncred $u)
    if [ "$n" != 0 ] && [ ! -f $MARK ]; then echo "ABORT: $u da co $n credential truoc khi setup (khong de)"; exit 3; fi
  done
  touch $MARK
  for u in chi.le tam.vu; do
    $KC set-password $R $C --username $u --new-password "$SPIKE_C_PW" || exit 1
  done
  mk_client spike-c-login "" || exit 1
  mk_client spike-c-short 15 || exit 1
  # lien ket (khong sua) scope tickets:read vao client ngan han de co token aud=tickets-mcp song 15s (ca het han o resource server)
  $KC update clients/$(cid spike-c-short)/optional-client-scopes/$(scid tickets:read) $R $C
  echo "setup ok" ;;
 status)
  echo "spike-c clients: [$($KC get clients $R -q search=true -q clientId=spike-c- --fields clientId --format csv --noquotes $C | grep '^spike-c-' | tr '\n' ' ')]"
  echo "credentials chi.le=$(ncred chi.le) tam.vu=$(ncred tam.vu)"
  fingerprint ;;
 cleanup)
  for c in $($KC get clients $R -q search=true -q clientId=spike-c- --fields clientId --format csv --noquotes $C | grep '^spike-c-'); do
    $KC delete clients/$(cid $c) $R $C && echo "deleted client $c"
  done
  for u in chi.le tam.vu; do
    id=$(uid $u)
    for cr in $($KC get users/$id/credentials $R --fields id --format csv --noquotes $C); do
      $KC delete users/$id/credentials/$cr $R $C && echo "deleted credential of $u"
    done
  done
  rm -f $MARK ;;
esac
