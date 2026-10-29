#!/usr/bin/env bash
# infra/scripts/backup.sh  (docs/design/04 §3.3) — `make backup`
# Dump các DB nghiệp vụ ra ./backups trên host. Khôi phục:
#   pg_restore -U postgres -d <db> --clean --if-exists <file>.dump
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p backups
TS=$(date +%Y%m%d-%H%M%S)
docker compose exec -T postgres pg_dumpall -U postgres --globals-only > "backups/globals-$TS.sql"
for db in gateway knowledge tickets analytics agent keycloak; do
  docker compose exec -T postgres pg_dump -U postgres -Fc -Z 6 "$db" > "backups/$db-$TS.dump"
done
sha256sum backups/*-"$TS".* > "backups/SHA256SUMS-$TS"
# giữ 7 bản
ls -1t backups/globals-*.sql | tail -n +8 | xargs -r rm -f
echo "Backup xong: backups/*-$TS.* (nhớ backup riêng audit-anchors/, không cùng nơi với dump)"
