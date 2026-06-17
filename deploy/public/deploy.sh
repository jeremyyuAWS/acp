#!/usr/bin/env bash
# Build the acp public-demo image in ACR and (re)deploy it as an externally-reachable
# Azure Container App, alongside the existing self-hosted Temporal env.
#
#   bash deploy/public/deploy.sh            # build + deploy, prints the URL + access code
#   ACP_ACCESS_CODE=hunter2 bash deploy/public/deploy.sh   # pin the gate passcode
#
# Reuses the Temporal standup's RG/ACR (override via ACP_RG / ACP_ACR). The demo
# scans the test account's Drive via its ADC creds, passed as an ACA secret.
# Per-user "Sign in with Google" replaces the passcode once a Web OAuth client exists.
set -euo pipefail
ACP="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ACP"

_retry() {  # ACA serializes revision writes; retry the conflict it raises when they overlap
  local i
  for i in 1 2 3 4 5 6; do
    if "$@" 2>/tmp/acp_az_err; then return 0; fi
    grep -qi "conflicting concurrent write" /tmp/acp_az_err || { cat /tmp/acp_az_err >&2; return 1; }
    echo "   ...ACA busy, retry $i"; sleep 12
  done
  cat /tmp/acp_az_err >&2; return 1
}

RG="${ACP_RG:-rg-acp-temporal}"
ACR="${ACP_ACR:-acptemporalacr3a51d3}"
APP="${ACP_APP:-acp-app}"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"
IMAGE="acp-app:${TAG}"
ADC_FILE="${GOOGLE_APPLICATION_CREDENTIALS:-$HOME/.config/gcloud/application_default_credentials.json}"
CODE="${ACP_ACCESS_CODE:-$(openssl rand -hex 6)}"
CLIENT_ID="${ACP_GOOGLE_CLIENT_ID:-}"   # set => per-user GIS sign-in, passcode gate off

echo "== 0/5 preflight =="
[ -f "$ADC_FILE" ] || { echo "no Drive ADC at $ADC_FILE — run: gcloud auth application-default login ..."; exit 1; }
RELEASE="spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll"
[ -f "$RELEASE" ] || { echo "missing .NET Office CLI at $RELEASE — build it first (dotnet build -c Release)"; exit 1; }
ENVNAME="${ACP_ENV:-$(az containerapp env list -g "$RG" --query '[0].name' -o tsv)}"
[ -n "$ENVNAME" ] || { echo "no Container Apps environment in $RG"; exit 1; }
echo "   rg=$RG acr=$ACR env=$ENVNAME app=$APP image=$IMAGE"

echo "== 1/5 vendor the Python PDF engine into the build context (compiled-equivalent: code only) =="
VEND="deploy/public/vendor/worker-python"
WP="${ACP_PDF_ENGINE_SRC:-$HOME/projects/_review-digital-accessibility/worker-python}"
rm -rf "$VEND" && mkdir -p "$VEND"
cp -R "$WP/analysers" "$WP/models" "$VEND/"
find "$VEND" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "   vendored $(find "$VEND" -name '*.py' | wc -l | tr -d ' ') engine modules"

echo "== 2/5 build image in ACR (remote; no local docker) =="
az acr build -r "$ACR" -t "$IMAGE" -f deploy/public/Dockerfile . -o none

echo "== 3/5 registry creds =="
ACRSERVER="$(az acr show -n "$ACR" --query loginServer -o tsv)"
ACRUSER="$(az acr credential show -n "$ACR" --query username -o tsv)"
ACRPW="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"

echo "== 4/5 (re)deploy Container App with external ingress =="
ADC_JSON="$(cat "$ADC_FILE")"
# Auth mode: per-user GIS (client id set, passcode off) vs demo (passcode gate on).
# Empty-string env values disable the unused lever.
if [ -n "$CLIENT_ID" ]; then
  MODE_ENV="ACP_GOOGLE_CLIENT_ID=$CLIENT_ID ACP_ACCESS_CODE="
  echo "   auth = per-user GIS (passcode gate disabled)"
else
  MODE_ENV="ACP_GOOGLE_CLIENT_ID= ACP_ACCESS_CODE=secretref:access-code"
  echo "   auth = demo (Basic-auth passcode gate)"
fi
if az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  _retry az containerapp secret set -g "$RG" -n "$APP" \
    --secrets "google-adc=$ADC_JSON" "access-code=$CODE" -o none
  _retry az containerapp registry set -g "$RG" -n "$APP" \
    --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
  _retry az containerapp update -g "$RG" -n "$APP" --image "$ACRSERVER/$IMAGE" \
    --set-env-vars ACP_GOOGLE_ADC=secretref:google-adc $MODE_ENV -o none
else
  az containerapp create -g "$RG" -n "$APP" --environment "$ENVNAME" \
    --image "$ACRSERVER/$IMAGE" \
    --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
    --target-port 8077 --ingress external \
    --secrets "google-adc=$ADC_JSON" "access-code=$CODE" \
    --env-vars ACP_GOOGLE_ADC=secretref:google-adc $MODE_ENV \
    --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 1 -o none
fi

echo "== 5/5 done =="
FQDN="$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
echo
echo "   URL:        https://$FQDN"
if [ -n "$CLIENT_ID" ]; then
  echo "   auth:       per-user 'Sign in with Google' (GIS)"
else
  echo "   access code: $CODE   (Basic auth — any username, this as the password)"
fi
echo "   health:     https://$FQDN/healthz"
