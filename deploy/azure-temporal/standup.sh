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
#   - Postgres TLS ENABLED + VERIFIED. KEY GOTCHA: the schema tool reads POSTGRES_TLS_*,
#     but the SERVER config template reads SQL_TLS_* (SQL_TLS_ENABLED / SQL_HOST_NAME /
#     SQL_HOST_VERIFICATION). Set only POSTGRES_TLS_* and the server connects PLAINTEXT,
#     which Azure (require_secure_transport=on) rejects -> "no usable database connection".
#     Both prefixes set here; verified against Azure's *.postgres.database.azure.com cert.
#   - Image served from a private ACR (not anonymous Docker Hub).
#   - Admin/registry passwords generated/fetched at runtime; not committed.
# Harden before customer use: Postgres on a private VNet (currently public +
#   "allow Azure services"); move secrets to Key Vault; ACR + Postgres auth via
#   managed identity instead of admin creds; add frontend mTLS.
#
# Hard-won lessons baked in (found on the real eastus2 standup):
#   - this subscription restricts Postgres flexible-server in eastus -> region probe.
#   - Temporal visibility schema needs btree_gin -> Azure Postgres azure.extensions allow-list.
#   - ACA anonymous docker.io pulls get rate-limited (HTTP 429) -> import to ACR
#     via Google's Docker Hub mirror (mirror.gcr.io), pull authenticated from ACR.
set -euo pipefail

SUB_NAME="${ACP_SUBSCRIPTION:-${ACP_SUB:-Azure subscription 1}}"
LOC="${ACP_LOC:-eastus}"
RLOCS="${ACP_RLOCS:-eastus2 centralus westus2 southcentralus westus3 canadacentral eastus}"
RG="${ACP_RG:-rg-acp-temporal}"
PG="${ACP_PG:-acp-temporal-pg-3a51d3}"
PGADMIN="${ACP_PGADMIN:-tmpladmin}"
ENVNAME="${ACP_ACA_ENV:-acp-temporal-env}"   # ACA environment NAME; ACP_ENV is refused below
APP="${ACP_APP:-temporal-frontend}"
ACR="${ACP_ACR:-acptemporalacr3a51d3}"
IMAGE="${ACP_IMAGE:-temporalio/auto-setup:1.25.2}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ENVFILE="$HERE/.env.local"

# $ACP_ENV named the ACA environment here, and api/core.py reads the same name to mean the
# *deployment* environment (IS_PROD). docs/production-hardening.md told operators to
# `export ACP_ENV=production` -- which this script would have read as an environment NAME, then
# happily CREATED an empty ACA environment called "production" (env show fails -> env create),
# while IS_PROD stayed false because ACP_ENV never reaches the container. Refuse the ambiguous
# name; the ACA environment is now ACP_ACA_ENV.
if [ -n "${ACP_ENV:-}" ]; then
  cat >&2 <<EOF
refusing to run: ACP_ENV is set ('$ACP_ENV'), and that name is ambiguous.
  - to name the Container Apps environment:  export ACP_ACA_ENV=<aca-env-name>
  - to mark an app as production:            export ACP_DEPLOY_ENV=production
EOF
  exit 1
fi

# Resolve the subscription ONCE and scope every `az` call to it (as deploy.sh and rollback.sh do;
# see tests/test_az_subscription_scope.py). This replaces `az account set --subscription "$SUB"`,
# which wrote the choice into ~/.azure/azureProfile.json -- a machine-global default shared by
# every shell and every concurrent process, since `az` has no per-invocation profile. A deploy
# elsewhere on this box observed exactly that: another process flipped the default mid-run and it
# failed looking for its ACR in a stranger's subscription. Here the stakes are higher, because
# `teardown` deletes an entire resource group.
#
# Pin the immutable ID, not the name: a rename cannot then retarget a run in flight.
SUB="$(az account show --subscription "$SUB_NAME" --query id -o tsv 2>/dev/null || true)"
[ -n "$SUB" ] || { echo "refusing to run: subscription '$SUB_NAME' does not resolve to one you can see -- run 'az login', or set ACP_SUBSCRIPTION" >&2; exit 1; }
AZ=(--subscription "$SUB")   # always non-empty; splice into EVERY az call
echo "subscription: $(az account show "${AZ[@]}" --query name -o tsv 2>/dev/null || echo '?') ($SUB)"

if [[ "${1:-}" == "teardown" ]]; then
  # `az group delete --yes --no-wait` is irreversible and asks nothing. It also reads RG from
  # $ACP_RG -- the SAME variable deploy/public/deploy.sh reads, where it defaults to the
  # PRODUCTION group `mdk-accessibility` (acp-app, the ACR, Postgres, Langfuse, Ollama, Redis,
  # the blob store). Export ACP_RG for a deploy, run `standup.sh teardown` in that same shell,
  # and the demo is gone. Nothing automated calls this script, so confirm before destroying.
  echo "About to DELETE resource group '$RG' and everything in it:"
  az resource list "${AZ[@]}" -g "$RG" --query "[].name" -o tsv 2>/dev/null | sed 's/^/    - /' || true
  if [ "${ACP_CONFIRM_TEARDOWN:-}" != "$RG" ]; then
    if [ -t 0 ]; then
      printf "Type the resource group name to confirm: "
      read -r reply
      [ "$reply" = "$RG" ] || { echo "aborted (got '$reply', expected '$RG')" >&2; exit 1; }
    else
      echo "refusing to tear down non-interactively: re-run with ACP_CONFIRM_TEARDOWN=$RG" >&2
      exit 1
    fi
  fi
  echo "Deleting resource group $RG ..."
  az group delete "${AZ[@]}" -n "$RG" --yes --no-wait
  exit 0
fi

echo "== 1/6 resource group =="
az group create "${AZ[@]}" -n "$RG" -l "$LOC" -o none

echo "== 2/6 postgres flexible server ($PG) — probing allowed regions, ~5-8 min =="
if az postgres flexible-server show "${AZ[@]}" -g "$RG" -n "$PG" -o none 2>/dev/null; then
  echo "  exists; reusing $ENVFILE"
else
  PGPWD="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)Aa1!"
  RLOC=""
  for r in $RLOCS; do
    echo "  trying $r ..."
    if az postgres flexible-server create "${AZ[@]}" \
        --resource-group "$RG" --name "$PG" --location "$r" \
        --tier Burstable --sku-name Standard_B1ms --version 16 --storage-size 32 \
        --admin-user "$PGADMIN" --admin-password "$PGPWD" \
        --public-access 0.0.0.0 --yes -o none 2>/tmp/acp_pgerr; then
      RLOC="$r"; echo "  ✔ created in $r"; break
    elif grep -qiE 'restricted|not available|NotAvailableForSubscription|capacity' /tmp/acp_pgerr; then
      echo "  ✗ $r unavailable, next"; continue
    else echo "  unexpected error:"; cat /tmp/acp_pgerr; exit 1; fi
  done
  [ -n "$RLOC" ] || { echo "no allowed region in: $RLOCS"; exit 1; }
  printf 'ACP_PG_FQDN=%s.postgres.database.azure.com\nACP_PGADMIN=%s\nACP_PGPWD=%s\nACP_RLOC=%s\n' \
    "$PG" "$PGADMIN" "$PGPWD" "$RLOC" > "$ENVFILE"
fi
# shellcheck disable=SC1090
source "$ENVFILE"
echo "  resource region: $ACP_RLOC"

echo "== 3/6 temporal databases + required extensions =="
az postgres flexible-server db create "${AZ[@]}" -g "$RG" -s "$PG" -d temporal -o none 2>/dev/null || true
az postgres flexible-server db create "${AZ[@]}" -g "$RG" -s "$PG" -d temporal_visibility -o none 2>/dev/null || true
az postgres flexible-server parameter set "${AZ[@]}" -g "$RG" -s "$PG" \
  -n azure.extensions -v BTREE_GIN,BTREE_GIST,PG_TRGM -o none

echo "== 4/6 container apps environment ($ACP_RLOC) =="
az containerapp env show "${AZ[@]}" -g "$RG" -n "$ENVNAME" -o none 2>/dev/null || \
  az containerapp env create "${AZ[@]}" -g "$RG" -n "$ENVNAME" --location "$ACP_RLOC" -o none

echo "== 5/6 private registry + image (via mirror.gcr.io to dodge docker.io 429) =="
az acr show "${AZ[@]}" -n "$ACR" -o none 2>/dev/null || \
  az acr create "${AZ[@]}" -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none
az acr repository show "${AZ[@]}" -n "$ACR" --image "$IMAGE" -o none 2>/dev/null || \
  az acr import "${AZ[@]}" -n "$ACR" --source "mirror.gcr.io/$IMAGE" --image "$IMAGE" -o none
ACRSERVER="$(az acr show "${AZ[@]}" -n "$ACR" --query loginServer -o tsv)"
ACRUSER="$(az acr credential show "${AZ[@]}" -n "$ACR" --query username -o tsv)"
ACRPW="$(az acr credential show "${AZ[@]}" -n "$ACR" --query 'passwords[0].value' -o tsv)"

echo "== 6/6 temporal server container app =="
az containerapp create "${AZ[@]}" -g "$RG" -n "$APP" --environment "$ENVNAME" \
  --image "$ACRSERVER/$IMAGE" \
  --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
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
    SQL_TLS_ENABLED=true "SQL_HOST_NAME=$ACP_PG_FQDN" SQL_HOST_VERIFICATION=true \
  -o none 2>/dev/null || \
az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" --image "$ACRSERVER/$IMAGE" -o none

FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
echo
echo "Temporal frontend (internal gRPC):  ${FQDN}:443  (reachable only inside env '$ENVNAME')"
echo "Validate:  az containerapp logs show --subscription $SUB -g $RG -n $APP --tail 50"
