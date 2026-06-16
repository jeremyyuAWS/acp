#!/usr/bin/env bash
# Stand up a self-hosted Temporal server on Azure Container Apps + Azure Postgres.
# MVP-grade: single-replica frontend via the temporalio/auto-setup image, standard
# (SQL) visibility on Postgres. Idempotent-ish; safe to re-run.
#
#   bash standup.sh           # provision
#   bash standup.sh teardown  # delete the whole resource group
#
# Security posture:
#   - Temporal frontend ingress is INTERNAL — reachable only from inside the
#     Container Apps environment (where the acp workers run). Nothing public.
#   - Postgres TLS is enabled WITH host verification (server name pinned).
#   - Admin password is generated at runtime into .env.local (gitignored) and set
#     as an ACA secret.
# Harden before customer use: Postgres on a private VNet (currently public +
#   "allow Azure services"); move secrets to Key Vault; add frontend mTLS.
set -euo pipefail

SUB="${ACP_SUB:-Azure subscription 1}"
LOC="${ACP_LOC:-eastus}"                       # resource-group metadata region
RLOCS="${ACP_RLOCS:-eastus2 centralus westus2 southcentralus westus3 canadacentral eastus}"
RG="${ACP_RG:-rg-acp-temporal}"
PG="${ACP_PG:-acp-temporal-pg-3a51d3}"         # must be globally unique
PGADMIN="${ACP_PGADMIN:-tmpladmin}"
ENVNAME="${ACP_ENV:-acp-temporal-env}"
APP="${ACP_APP:-temporal-frontend}"
IMAGE="${ACP_IMAGE:-temporalio/auto-setup:1.25.2}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ENVFILE="$HERE/.env.local"

az account set --subscription "$SUB"

if [[ "${1:-}" == "teardown" ]]; then
  echo "Deleting resource group $RG ..."; az group delete -n "$RG" --yes --no-wait; exit 0
fi

echo "== 1/5 resource group =="
az group create -n "$RG" -l "$LOC" -o none

echo "== 2/5 postgres flexible server ($PG) — probing allowed regions, ~5-8 min =="
if az postgres flexible-server show -g "$RG" -n "$PG" -o none 2>/dev/null; then
  echo "  exists; reusing $ENVFILE"
else
  PGPWD="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)Aa1!"
  RLOC=""
  for r in $RLOCS; do
    echo "  trying $r ..."
    if az postgres flexible-server create \
        --resource-group "$RG" --name "$PG" --location "$r" \
        --tier Burstable --sku-name Standard_B1ms --version 16 --storage-size 32 \
        --admin-user "$PGADMIN" --admin-password "$PGPWD" \
        --public-access 0.0.0.0 --yes -o none 2>/tmp/acp_pgerr; then
      RLOC="$r"; echo "  ✔ created in $r"; break
    elif grep -qiE 'restricted|not available|NotAvailableForSubscription|capacity' /tmp/acp_pgerr; then
      echo "  ✗ $r unavailable, next"; continue
    else
      echo "  unexpected error:"; cat /tmp/acp_pgerr; exit 1
    fi
  done
  [ -n "$RLOC" ] || { echo "no allowed region in: $RLOCS"; exit 1; }
  printf 'ACP_PG_FQDN=%s.postgres.database.azure.com\nACP_PGADMIN=%s\nACP_PGPWD=%s\nACP_RLOC=%s\n' \
    "$PG" "$PGADMIN" "$PGPWD" "$RLOC" > "$ENVFILE"
fi
# shellcheck disable=SC1090
source "$ENVFILE"
echo "  resource region: $ACP_RLOC"

echo "== 3/5 temporal databases =="
az postgres flexible-server db create -g "$RG" -s "$PG" -d temporal -o none 2>/dev/null || true
az postgres flexible-server db create -g "$RG" -s "$PG" -d temporal_visibility -o none 2>/dev/null || true

echo "== 4/5 container apps environment ($ACP_RLOC) =="
az containerapp env show -g "$RG" -n "$ENVNAME" -o none 2>/dev/null || \
  az containerapp env create -g "$RG" -n "$ENVNAME" --location "$ACP_RLOC" -o none

echo "== 5/5 temporal server container app =="
az containerapp create -g "$RG" -n "$APP" --environment "$ENVNAME" \
  --image "$IMAGE" \
  --target-port 7233 --transport http2 --ingress internal \
  --min-replicas 1 --max-replicas 1 --cpu 1.0 --memory 2.0Gi \
  --secrets "pgpwd=$ACP_PGPWD" \
  --env-vars \
    DB=postgres12 \
    "POSTGRES_SEEDS=$ACP_PG_FQDN" DB_PORT=5432 \
    "POSTGRES_USER=$ACP_PGADMIN" "POSTGRES_PWD=secretref:pgpwd" \
    DBNAME=temporal VISIBILITY_DBNAME=temporal_visibility \
    SKIP_DB_CREATE=true \
    POSTGRES_TLS_ENABLED=true "POSTGRES_TLS_SERVER_NAME=$ACP_PG_FQDN" \
  -o none

FQDN="$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
echo
echo "Temporal frontend (internal gRPC):  ${FQDN}:443  (reachable only inside env '$ENVNAME')"
echo "Validate:  az containerapp logs show -g $RG -n $APP --tail 50   # expect schema setup + 'Started Temporal server'"
