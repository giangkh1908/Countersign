#!/bin/sh
# infra/redis/entrypoint.sh  (docs/design/04 §2.3)
# Render /tmp/users.acl từ template + SHA256 của các secret; thiếu secret -> hash "0" (không hợp lệ,
# fail-closed). Placeholder không có trong template (vd redis-cache) bị sed bỏ qua.
set -eu
h() {
  if [ -f "/run/secrets/$1" ]; then
    printf %s "$(cat "/run/secrets/$1")" | sha256sum | cut -d' ' -f1
  else
    echo 0
  fi
}
sed -e "s/@@REDIS_GATEWAY@@/$(h redis_gateway_password)/" \
    -e "s/@@REDIS_TICKETS@@/$(h redis_tickets_password)/" \
    -e "s/@@REDIS_DOCS@@/$(h redis_docs_password)/" \
    -e "s/@@REDIS_ANALYTICS@@/$(h redis_analytics_password)/" \
    -e "s/@@REDIS_BFF@@/$(h redis_bff_password)/" \
    -e "s/@@REDIS_OPS@@/$(h redis_ops_password)/" \
    -e "s/@@REDIS_HEALTH@@/$(h redis_health_password)/" \
    /etc/redis/users.acl.tmpl > /tmp/users.acl
chmod 600 /tmp/users.acl
exec "$@"
