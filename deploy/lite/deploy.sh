#!/usr/bin/env bash
# Build the ACP Lite image in ACR and (re)deploy it as an externally-reachable Azure Container
# App, beside the existing acp-app. Separate infra, deliberately: its own container app, its own
# image, its own revisions and its own URL, so a Lite deploy can never restart, scale or roll
# back the production control plane.
#
#   bash deploy/lite/deploy.sh                    # deploy/refresh acp-lite       (prod-like)
#   ACP_LITE_ENV=staging bash deploy/lite/deploy.sh   # deploy/refresh acp-lite-staging
#
# Reuses acp-app's resource group, ACR and Container Apps environment (override via ACP_RG /
# ACP_ACR / ACP_ACA_ENV) — the same reuse deploy/public/deploy.sh already does with the Temporal
# standup's. Sharing an ACA *environment* shares the network and Log Analytics workspace, not
# compute or scaling: each container app keeps its own replicas, revisions and ingress.
#
# WHAT THIS DOES NOT NEED, and it is the point of the app. No database, no Redis, no Langfuse, no
# Google ADC, no access code, no worker tier, no blob store. ACP Lite is one static page: nothing
# to configure means nothing to leak and nothing to get wrong at 2am. If you find yourself adding
# a secret to this script, the thing you are deploying is no longer ACP Lite.
set -euo pipefail
ACP="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ACP"

# ACA serializes revision writes and raises on overlap; same retry deploy/public/deploy.sh uses.
_retry() {
  local i
  for i in 1 2 3 4 5 6; do
    if "$@" 2>/tmp/acp_lite_az_err; then return 0; fi
    grep -qi "conflicting concurrent write" /tmp/acp_lite_az_err || { cat /tmp/acp_lite_az_err >&2; return 1; }
    echo "   ...ACA busy, retry $i"; sleep 12
  done
  cat /tmp/acp_lite_az_err >&2; return 1
}

RG="${ACP_RG:-mdk-accessibility}"
ACR="${ACP_ACR:-mdkaccessibilityacr}"
LITE_ENV="${ACP_LITE_ENV:-prod}"

case "$LITE_ENV" in
  prod)    APP="${ACP_LITE_APP:-acp-lite}" ;;
  staging) APP="${ACP_LITE_APP:-acp-lite-staging}" ;;
  *) echo "ACP_LITE_ENV must be 'prod' or 'staging' (got '$LITE_ENV')" >&2; exit 2 ;;
esac

# Unique per build. ACA caches images by tag, so a reused tag is never re-pulled and a deploy
# silently ships the previous bytes — the timestamp suffix is what makes "I redeployed and
# nothing changed" impossible. Same reasoning, same shape, as deploy/public/deploy.sh's TAG.
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo manual)-$(date +%s)"
IMAGE="acp-lite:${TAG}"

command -v az >/dev/null 2>&1 || { echo "az CLI not found — install it and 'az login' first" >&2; exit 1; }
az account show -o none 2>/dev/null || { echo "not logged in — run 'az login'" >&2; exit 1; }

AZ=()
[ -n "${ACP_SUBSCRIPTION:-}" ] && AZ=(--subscription "$ACP_SUBSCRIPTION")

ENVNAME="${ACP_ACA_ENV:-$(az containerapp env list "${AZ[@]}" -g "$RG" --query '[0].name' -o tsv)}"
[ -n "$ENVNAME" ] || { echo "no Container Apps environment found in RG $RG — set ACP_ACA_ENV" >&2; exit 1; }

echo "== ACP Lite deploy =="
echo "   env=$LITE_ENV rg=$RG acr=$ACR aca-env=$ENVNAME app=$APP image=$IMAGE"

# ── 1/3 build in ACR (remote; no local docker needed) ───────────────────────────────────────
# Build context is the repo root so the Dockerfile's COPY paths match the ones a reader sees in
# the tree. The image is small enough that there is no base-image split to maintain here.
echo "== 1/3 build image in ACR =="
az acr build "${AZ[@]}" -r "$ACR" -t "$IMAGE" -f deploy/lite/Dockerfile .

ACRSERVER="$(az acr show "${AZ[@]}" -n "$ACR" --query loginServer -o tsv)"
ACRUSER="$(az acr credential show "${AZ[@]}" -n "$ACR" --query username -o tsv)"
ACRPW="$(az acr credential show "${AZ[@]}" -n "$ACR" --query 'passwords[0].value' -o tsv)"

# ── 2/3 create or update the container app ──────────────────────────────────────────────────
# min-replicas 0: a prototype nobody is looking at should cost nothing. The cold start is a few
# hundred milliseconds for a static nginx, which is the one case where scale-to-zero has no
# user-visible downside — unlike the control plane, where it would drop a running scan.
echo "== 2/3 deploy container app =="
if az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" -o none 2>/dev/null; then
  _retry az containerapp registry set "${AZ[@]}" -g "$RG" -n "$APP" \
    --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
  _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" \
    --image "$ACRSERVER/$IMAGE" -o none
else
  _retry az containerapp create "${AZ[@]}" -g "$RG" -n "$APP" \
    --environment "$ENVNAME" \
    --image "$ACRSERVER/$IMAGE" \
    --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
    --target-port 8080 --ingress external \
    --min-replicas 0 --max-replicas 2 \
    --cpu 0.25 --memory 0.5Gi \
    -o none
fi

# ── 3/3 report ──────────────────────────────────────────────────────────────────────────────
FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query 'properties.configuration.ingress.fqdn' -o tsv)"
URL="https://$FQDN"

echo "== 3/3 verify =="
# Read the exit status of curl itself, never of a pipeline — a `curl | grep` reports grep's
# status and cannot tell "no match" from "curl never ran" (CLAUDE.md, "Verify before you
# diagnose"). Retried because a fresh revision takes a moment to accept traffic.
CODE=""
for i in 1 2 3 4 5 6 7 8; do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/healthz" || echo "000")"
  [ "$CODE" = "200" ] && break
  echo "   ...waiting for ingress (got $CODE, attempt $i)"; sleep 5
done

echo
if [ "$CODE" = "200" ]; then
  echo "   ACP Lite ($LITE_ENV) is up:  $URL"
else
  echo "   DEPLOYED, BUT /healthz returned '$CODE' rather than 200 — the revision may still be" >&2
  echo "   starting, or ingress is misconfigured. Check:" >&2
  echo "     az containerapp logs show -g $RG -n $APP --tail 50" >&2
  exit 1
fi
