#!/usr/bin/env bash
# Kort 88: kör om DHL-sandboxtestet med utvecklingskopian av modulen
# (rättelserna för kontaktnamn och pallkod) och visar utfallet.
# Inget skrivs i staging: testet rullar tillbaka allt, modulen monteras skrivskyddat.
set -euo pipefail
cd /home/chrille/dev/projects/arc_delivery_dhl
DEV=1 bash scripts/run_sandbox.sh scripts/sandbox_acceptance.py /var/log/odoo/dhl-sandbox-test/run2.log 2>&1 | sed -n '/^SUMMARY/,$p' | cut -c1-420
echo "== DHL:s felbesked"
grep -o "Response body: .*" /data/staging/plastshop-staging/logs/dhl-sandbox-test/run2.log | cut -c1-400 || echo "inga"
