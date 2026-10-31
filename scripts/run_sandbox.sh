#!/usr/bin/env bash
# Kör ett odoo shell-skript mot staging.plastshop.se i en engångscontainer med
# utgående nät (stagings eget nät är internt med flit). Sandbox-nyckeln läses ur
# projektets .env och skrivs aldrig ut. Skripten rullar själva tillbaka.
#   bash scripts/run_sandbox.sh scripts/sandbox_acceptance.py [loggfil]
set -euo pipefail
cd "$(dirname "$0")/.."
script="$1"
log="${2:-/dev/null}"
key=$(awk -F= '$1=="DHL_SANDBOX_API_KEY"{print $2}' .env | tr -d "\"' ")
pgpass=$(docker exec plastshop-staging-web printenv PASSWORD)
# DEV=1 lägger utvecklingskopian av modulen över stagings, skrivskyddat, så att
# en ändring kan provas mot sandboxen utan att staging driftsätts.
extra=()
if [ "${DEV:-0}" = 1 ]; then
  extra=(-v "$PWD/arc_delivery_dhl:/mnt/extra-addons/arc_delivery_dhl:ro")
fi
cid=$(docker create -i --rm --user 1000:101 --volumes-from plastshop-staging-web "${extra[@]}" \
  --network plastshop-staging_staging-net \
  -e DHL_SANDBOX_API_KEY="$key" -e PGPASS="$pgpass" -e LOGF="$log" \
  --entrypoint sh odoo:18-plastshop -c \
  'odoo shell -c /etc/odoo/odoo.conf -d staging.plastshop.se --no-http --logfile="$LOGF" --db_host=db --db_user=odoo18 --db_password="$PGPASS"')
docker network connect bridge "$cid"
docker start -ai "$cid" < "$script"
