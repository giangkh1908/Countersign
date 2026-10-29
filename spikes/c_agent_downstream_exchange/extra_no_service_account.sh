KC=/opt/keycloak/bin/kcadm.sh; C="--config /tmp/kcadm-spike-c.config"
$KC config credentials --server http://localhost:8080 --realm master --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" --password "$(cat /run/secrets/kc_admin_password)" $C >/dev/null
U=$($KC get users -r acme -q username=chi.le -q exact=true --fields id --format csv --noquotes $C)
case "$1" in
 setup)
  N=$($KC get users/$U/credentials -r acme $C | grep -c '"type"'); [ "$N" = 0 ] || { echo "chi.le has creds, abort"; exit 1; }
  $KC create clients -r acme $C -s clientId=spike-c-nosa -s publicClient=false -s secret="$SPIKE_C_SECRET" -s directAccessGrantsEnabled=true -s standardFlowEnabled=false -s serviceAccountsEnabled=false -s fullScopeAllowed=false -s 'attributes={"standard.token.exchange.enabled":"true"}' >/dev/null
  CID=$($KC get clients -r acme -q clientId=spike-c-nosa --fields id --format csv --noquotes $C)
  $KC create clients/$CID/protocol-mappers/models -r acme $C -s name=aud-self -s protocol=openid-connect -s protocolMapper=oidc-audience-mapper -s 'config={"included.client.audience":"spike-c-nosa","access.token.claim":"true"}' >/dev/null
  for s in acme-claims; do SID=$($KC get client-scopes -r acme $C --fields id,name --format csv --noquotes | grep ",$s$" | cut -d, -f1); $KC update clients/$CID/default-client-scopes/$SID -r acme $C; done
  SID=$($KC get client-scopes -r acme $C --fields id,name --format csv --noquotes | grep ",tickets:read$" | cut -d, -f1); $KC update clients/$CID/optional-client-scopes/$SID -r acme $C
  $KC set-password -r acme $C --userid $U --new-password "$SPIKE_C_PW" --temporary=false && echo setup-ok ;;
 cleanup)
  CID=$($KC get clients -r acme -q clientId=spike-c-nosa --fields id --format csv --noquotes $C); [ -n "$CID" ] && $KC delete clients/$CID -r acme $C && echo deleted-client
  for cid in $($KC get users/$U/credentials -r acme $C --fields id --format csv --noquotes); do $KC delete users/$U/credentials/$cid -r acme $C; done
  echo "clients: $($KC get clients -r acme --fields clientId --format csv --noquotes $C | grep spike-c | tr '\n' ' ')"; echo "chi.le creds: $($KC get users/$U/credentials -r acme $C | grep -c '"type"')" ;;
esac
