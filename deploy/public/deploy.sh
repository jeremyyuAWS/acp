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

RG="${ACP_RG:-mdk-accessibility}"
ACR="${ACP_ACR:-mdkaccessibilityacr}"
APP="${ACP_APP:-acp-app}"
# unique per build: ACA caches images by tag, so a reused tag (e.g. uncommitted
# working tree → same HEAD sha twice) is never re-pulled. Timestamp suffix forces it.
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo manual)-$(date +%s)"
IMAGE="acp-app:${TAG}"
ADC_FILE="${ACP_GOOGLE_ADC_FILE:-${GOOGLE_APPLICATION_CREDENTIALS:-$HOME/.config/gcloud/application_default_credentials.json}}"
CODE="${ACP_ACCESS_CODE:-$(openssl rand -hex 6)}"
CLIENT_ID="${ACP_GOOGLE_CLIENT_ID:-}"   # set => per-user GIS sign-in, passcode gate off
DATABASE_URL="${ACP_DATABASE_URL:-}"    # set => Postgres backend; unset => SQLite (single-instance only)
LF_HOST="${LANGFUSE_HOST:-https://acp-langfuse.greenwater-4bf2c997.eastus2.azurecontainerapps.io}"
LF_PK="${LANGFUSE_PUBLIC_KEY:-pk-lf-655083d12dacf12febf1f1e8d2293905}"  # acp-compliance project — the one the demo VIEWS (must match LANGFUSE_INIT_PROJECT_* on acp-langfuse, pairs with sk-lf-d1cd10699…). Override via env if needed.
LF_SK="${LANGFUSE_SECRET_KEY:-}"       # secret — must be passed via env; not baked in
HITL_WEBHOOK="${HITL_WEBHOOK_URL:-}"   # set => POST to this URL when HITL items are queued
DEMO_DRIVE_KEY="${ACP_DEMO_DRIVE_KEY:-}"  # set => enables server-side ADC Drive scan for E2E tests
E2E_KEY="${ACP_E2E_KEY:-}"                # set => X-E2E-Key bypass for smoke tests; leave unset in prod if unused
# Remediated-output Blob store (ADR 0010) — managed identity auth, no key. The account +
# container + acp-app's system-assigned identity + Storage Blob Data Contributor role
# grant are one-time infra setup (not this script's job); this just points the app at it.
BLOB_ACCOUNT="${ACP_BLOB_ACCOUNT:-acpremediatedstore}"

echo "== 0/5 preflight =="
# Pin the subscription when asked (matches rollback.sh) -- the az default can
# point elsewhere when other work shares this machine. NOTE: az has no
# per-invocation profile, so this updates the az CLI's global default.
if [ -n "${ACP_SUBSCRIPTION:-}" ]; then
  az account set --subscription "$ACP_SUBSCRIPTION"
  echo "   subscription = $ACP_SUBSCRIPTION (az default updated)"
fi
# Inherit ACP_GOOGLE_CLIENT_ID from the existing ACA if not provided locally, so a plain
# redeploy doesn't accidentally clear or overwrite the already-configured OAuth client id.
if [ -z "$CLIENT_ID" ] && az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  CLIENT_ID="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='ACP_GOOGLE_CLIENT_ID'].value | [0]" \
    -o tsv 2>/dev/null || echo "")"
  [ -n "$CLIENT_ID" ] && echo "   client_id = inherited from existing deployment ($CLIENT_ID)"
fi
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
cp -R "$WP/analysers" "$WP/models" "$WP/remediation" "$VEND/"  # remediation/ = ADR 0005 step 4 (PDF fixers)
find "$VEND" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "   vendored $(find "$VEND" -name '*.py' | wc -l | tr -d ' ') engine modules"

echo "== 2/5 build image in ACR (remote; no local docker) =="
# Build provenance (ADR: CalVer-style) baked into the image → surfaced in /healthz +
# the hub footer + the app header. Computed here so every deploy stamps a fresh version
# (.git is excluded from the build context, so the image can't derive it itself).
BUILD_VERSION="$(date -u +%Y).$(( 10#$(date -u +%m) )).$(( 10#$(date -u +%d) ))"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "   version $BUILD_VERSION · built $BUILD_TIME"
az acr build -r "$ACR" -t "$IMAGE" -f deploy/public/Dockerfile \
  --build-arg BUILD_VERSION="$BUILD_VERSION" --build-arg BUILD_TIME="$BUILD_TIME" . -o none

echo "== 3/5 registry creds =="
ACRSERVER="$(az acr show -n "$ACR" --query loginServer -o tsv)"
ACRUSER="$(az acr credential show -n "$ACR" --query username -o tsv)"
ACRPW="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"

echo "== 4/5 (re)deploy Container App with external ingress =="
ADC_JSON="$(cat "$ADC_FILE")"
# Auth mode: per-user GIS (client id set, passcode off) vs demo (passcode gate on).
if [ -n "$CLIENT_ID" ]; then
  MODE_ENV="ACP_GOOGLE_CLIENT_ID=$CLIENT_ID ACP_ACCESS_CODE="
  echo "   auth = per-user GIS (passcode gate disabled)"
else
  MODE_ENV="ACP_GOOGLE_CLIENT_ID= ACP_ACCESS_CODE=secretref:access-code"
  echo "   auth = demo (Basic-auth passcode gate)"
fi
# Build secrets array — always pass each secret as its own element so values
# containing '=' or '?' (e.g. a Postgres URL with ?sslmode=require) are never
# split or mangled by either the shell or the az CLI parser.
SECRETS=("google-adc=$ADC_JSON" "access-code=$CODE")
# Database: Postgres secret (if DATABASE_URL set) or inherit the existing one.
# IMPORTANT: a bare redeploy must NOT silently downgrade Postgres → SQLite (that
# loses persistence + skips Grafana). So when ACP_DATABASE_URL isn't passed we
# INHERIT the already-configured secretref instead of clearing it.
if [ -n "$DATABASE_URL" ]; then
  SECRETS+=("database-url=$DATABASE_URL")
  DB_ENV="DATABASE_URL=secretref:database-url"
  echo "   db = Postgres (DATABASE_URL set)"
else
  EXISTING_DB="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='DATABASE_URL'].secretRef | [0]" \
    -o tsv 2>/dev/null || echo "")"
  if [ -n "$EXISTING_DB" ]; then
    DB_ENV="DATABASE_URL=secretref:$EXISTING_DB"
    echo "   db = Postgres (inherited from existing deployment)"
  else
    DB_ENV="DATABASE_URL="
    echo "   db = SQLite (no DATABASE_URL set or inherited — single-instance only)"
  fi
fi
# Langfuse observability (optional — no-ops when absent). A bare redeploy (LF_SK not
# passed) must NOT silently DISABLE Langfuse — that breaks every "View trace" link. So
# when LANGFUSE_SECRET_KEY isn't provided we INHERIT the already-configured secretrefs +
# host, mirroring the DATABASE_URL guard above. Only set fresh when LF_SK is passed.
if [ -n "$LF_SK" ]; then
  SECRETS+=("langfuse-pk=$LF_PK" "langfuse-sk=$LF_SK")
  LF_ENV="LANGFUSE_HOST=$LF_HOST LANGFUSE_PUBLIC_KEY=secretref:langfuse-pk LANGFUSE_SECRET_KEY=secretref:langfuse-sk"
  echo "   langfuse = enabled ($LF_HOST)"
else
  EXISTING_LF_SK="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='LANGFUSE_SECRET_KEY'].secretRef | [0]" -o tsv 2>/dev/null || echo "")"
  EXISTING_LF_PK="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='LANGFUSE_PUBLIC_KEY'].secretRef | [0]" -o tsv 2>/dev/null || echo "")"
  EXISTING_LF_HOST="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='LANGFUSE_HOST'].value | [0]" -o tsv 2>/dev/null || echo "")"
  if [ -n "$EXISTING_LF_SK" ]; then
    LF_ENV="LANGFUSE_HOST=${EXISTING_LF_HOST:-$LF_HOST} LANGFUSE_PUBLIC_KEY=secretref:$EXISTING_LF_PK LANGFUSE_SECRET_KEY=secretref:$EXISTING_LF_SK"
    echo "   langfuse = inherited from existing deployment"
  else
    LF_ENV=""
    echo "   langfuse = disabled (LANGFUSE_SECRET_KEY not set or inherited)"
  fi
fi
# HITL webhook (optional — no-ops when absent).
if [ -n "$HITL_WEBHOOK" ]; then
  HITL_ENV="HITL_WEBHOOK_URL=$HITL_WEBHOOK"
  echo "   hitl webhook = $HITL_WEBHOOK"
else
  HITL_ENV=""
  echo "   hitl webhook = disabled (HITL_WEBHOOK_URL not set)"
fi
# Demo Drive key — enables server-side ADC Drive scan for E2E tests without GIS.
if [ -n "$DEMO_DRIVE_KEY" ]; then
  SECRETS+=("demo-drive-key=$DEMO_DRIVE_KEY")
  DEMO_ENV="ACP_DEMO_DRIVE_KEY=secretref:demo-drive-key"
  echo "   demo drive key = set (E2E Drive scan enabled)"
else
  # Inherit from existing deployment so a plain redeploy doesn't clear it.
  EXISTING_DEMO_KEY="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='ACP_DEMO_DRIVE_KEY'].secretRef | [0]" \
    -o tsv 2>/dev/null || echo "")"
  DEMO_ENV="${EXISTING_DEMO_KEY:+ACP_DEMO_DRIVE_KEY=secretref:$EXISTING_DEMO_KEY}"
  echo "   demo drive key = inherited"
fi
# E2E smoke-test key — enables X-E2E-Key auth bypass; inherit if not set.
if [ -n "$E2E_KEY" ]; then
  SECRETS+=("e2e-key=$E2E_KEY")
  E2E_ENV="ACP_E2E_KEY=secretref:e2e-key"
  echo "   e2e key = set"
else
  EXISTING_E2E="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='ACP_E2E_KEY'].secretRef | [0]" \
    -o tsv 2>/dev/null || echo "")"
  E2E_ENV="${EXISTING_E2E:+ACP_E2E_KEY=secretref:$EXISTING_E2E}"
  echo "   e2e key = inherited"
fi
# Async worker pool — ACP_WORKERS=N runs N in-process job workers. Plain (non-secret)
# env vars; inherit when not passed so a bare redeploy keeps them.
_inherit_env() {  # $1 = var name → echoes "NAME=value" if currently set, else ""
  local v; v="$(az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='$1'].value | [0]" -o tsv 2>/dev/null || echo "")"
  [ -n "$v" ] && echo "$1=$v"
}
WORKERS_ENV="${ACP_WORKERS:+ACP_WORKERS=$ACP_WORKERS}"; [ -z "$WORKERS_ENV" ] && WORKERS_ENV="$(_inherit_env ACP_WORKERS)"
EMAILS_ENV="${ACP_ALLOWED_EMAILS:+ACP_ALLOWED_EMAILS=$ACP_ALLOWED_EMAILS}"; [ -z "$EMAILS_ENV" ] && EMAILS_ENV="$(_inherit_env ACP_ALLOWED_EMAILS)"
BLOB_ENV="ACP_BLOB_ACCOUNT=$BLOB_ACCOUNT"
echo "   workers = ${ACP_WORKERS:-${WORKERS_ENV:+inherited}}${WORKERS_ENV:+}"
echo "   allowed emails = ${ACP_ALLOWED_EMAILS:-${EMAILS_ENV:+inherited}}"
echo "   blob account = $BLOB_ACCOUNT"
if az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  _retry az containerapp secret set -g "$RG" -n "$APP" \
    --secrets "${SECRETS[@]}" -o none
  _retry az containerapp registry set -g "$RG" -n "$APP" \
    --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
  _retry az containerapp update -g "$RG" -n "$APP" --image "$ACRSERVER/$IMAGE" \
    --set-env-vars ACP_GOOGLE_ADC=secretref:google-adc $MODE_ENV $DB_ENV $LF_ENV $HITL_ENV $DEMO_ENV $E2E_ENV $WORKERS_ENV $EMAILS_ENV $BLOB_ENV -o none
else
  az containerapp create -g "$RG" -n "$APP" --environment "$ENVNAME" \
    --image "$ACRSERVER/$IMAGE" \
    --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
    --target-port 8077 --ingress external \
    --secrets "${SECRETS[@]}" \
    --env-vars ACP_GOOGLE_ADC=secretref:google-adc $MODE_ENV $DB_ENV $LF_ENV $HITL_ENV $DEMO_ENV $E2E_ENV $WORKERS_ENV $EMAILS_ENV $BLOB_ENV \
    --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 1 -o none
fi

echo "== 5/5 done =="
FQDN="$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"

# ── Optional: standalone ACP Grafana ─────────────────────────────────────────
# Build + deploy only when ACP_DATABASE_URL (Postgres) is set — Grafana needs
# it to provision the datasource. Skipped for SQLite-only deployments.
GF_APP="acp-grafana"
GF_IMAGE="acp-grafana:${TAG}"
if [ -n "$DATABASE_URL" ]; then
  echo "== Grafana: build + deploy ACP-specific dashboard container =="
  # Parse Postgres DSN → Grafana env vars.
  # Expected format: postgresql://user:pass@host[:port]/db?...
  _PG_USER="$(echo "$DATABASE_URL" | sed 's|.*://\([^:]*\):.*|\1|')"
  _PG_PASS="$(echo "$DATABASE_URL" | sed 's|.*://[^:]*:\([^@]*\)@.*|\1|')"
  _PG_HOST="$(echo "$DATABASE_URL" | sed 's|.*@\([^/]*\)/.*|\1|')"
  _PG_DB="$(echo "$DATABASE_URL"   | sed 's|.*/\([^?]*\).*|\1|')"
  az acr build -r "$ACR" -t "$GF_IMAGE" -f deploy/grafana/Dockerfile deploy/grafana -o none
  if az containerapp show -g "$RG" -n "$GF_APP" -o none 2>/dev/null; then
    # Ensure the Grafana app can pull from the private ACR before updating its
    # image (an older acp-grafana may have been created without these creds,
    # which fails the revision with UNAUTHORIZED).
    _retry az containerapp registry set -g "$RG" -n "$GF_APP" \
      --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
    _retry az containerapp update -g "$RG" -n "$GF_APP" --image "$ACRSERVER/$GF_IMAGE" \
      --set-env-vars \
        ACP_GRAFANA_PG_HOST="$_PG_HOST" \
        ACP_GRAFANA_PG_DB="$_PG_DB" \
        ACP_GRAFANA_PG_USER="$_PG_USER" \
        ACP_GRAFANA_PG_PASS="$_PG_PASS" \
        GF_AUTH_ANONYMOUS_ENABLED=true \
        GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
        GF_AUTH_DISABLE_LOGIN_FORM=false \
      -o none
  else
    az containerapp create -g "$RG" -n "$GF_APP" --environment "$ENVNAME" \
      --image "$ACRSERVER/$GF_IMAGE" \
      --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
      --target-port 3000 --ingress external \
      --env-vars \
        ACP_GRAFANA_PG_HOST="$_PG_HOST" \
        ACP_GRAFANA_PG_DB="$_PG_DB" \
        ACP_GRAFANA_PG_USER="$_PG_USER" \
        ACP_GRAFANA_PG_PASS="$_PG_PASS" \
        GF_AUTH_ANONYMOUS_ENABLED=true \
        GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
        GF_AUTH_DISABLE_LOGIN_FORM=false \
      --cpu 0.5 --memory 1.0Gi --min-replicas 1 --max-replicas 1 -o none
  fi
  GF_FQDN="$(az containerapp show -g "$RG" -n "$GF_APP" --query properties.configuration.ingress.fqdn -o tsv)"
  echo "   Grafana:    https://$GF_FQDN   (anonymous viewer; sign in as admin for edits)"
else
  echo "   Grafana:    skipped — ACP_DATABASE_URL not set (SQLite mode)"
fi
echo
echo "   URL:        https://$FQDN"
if [ -n "$CLIENT_ID" ]; then
  echo "   auth:       per-user 'Sign in with Google' (GIS)"
else
  echo "   access code: $CODE   (Basic auth — any username, this as the password)"
fi
echo "   health:     https://$FQDN/healthz"
