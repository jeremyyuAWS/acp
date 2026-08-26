#!/usr/bin/env bash
# Provision (or re-provision) the STAGING environment that .github/workflows/deploy-staging.yml
# deploys to on every green main. Run this ONCE by hand, from a machine that can already deploy
# production; after it succeeds, staging auto-deploys unattended like the workflow describes.
#
#   ACP_SUBSCRIPTION=<prod-sub-id> \
#   ACP_STAGING_DATABASE_URL='postgresql://user:pass@staging-host/acp?sslmode=require' \
#   ACP_STAGING_REDIS_URL='redis://staging-redis:6379/0' \
#   bash deploy/public/staging_up.sh
#
# WHY A SEPARATE SCRIPT and not just `ACP_APP=acp-app-staging bash deploy.sh`:
#
#   1. deploy.sh reads DATABASE_URL / REDIS_URL / LANGFUSE_* straight from the environment, and a
#      shell that just deployed prod has prod's values exported. Pointing staging at the prod DB
#      would have staging WRITE to production data. This wrapper takes ONLY staging-prefixed vars
#      (ACP_STAGING_*), so nothing prod can leak in by inheritance — that isolation is the point.
#   2. Staging mirrors prod's SPLIT TIER (acp-app-staging + acp-worker-staging), because that is
#      what redeploy.sh — which the workflow runs unchanged — expects: it updates and health-checks
#      BOTH apps. A single-container staging on SQLite would deploy fine and then fail to catch the
#      worker-tier and Postgres problems staging exists to catch. Split tier REQUIRES a shared
#      Postgres and Redis, so this script refuses SQLite rather than provision a staging that lies.
#   3. It surfaces the exact `gh variable set STAGING_FQDN` line at the end — that variable is the
#      switch that un-dormants deploy-staging.yml, so provisioning and enabling are one flow.
#
# This is also the FIRST real exercise of the worker-tier split (ADR 0013 §2), which deploy.sh
# notes is "codified but not yet exercised against live infra". Staging is the right place to shake
# out any az-CLI specifics — a failure here never touches production.
set -euo pipefail

ACP="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ACP"

die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

APP_NAME="${ACP_STAGING_APP_NAME:-acp-app-staging}"
WORKER_NAME="${ACP_STAGING_WORKER_NAME:-acp-worker-staging}"

# ── required staging inputs (prefixed, so prod's exported env cannot leak in) ─────────────────
DB="${ACP_STAGING_DATABASE_URL:-}"
REDIS="${ACP_STAGING_REDIS_URL:-}"
[ -n "$DB" ] || die "ACP_STAGING_DATABASE_URL is required. Staging mirrors prod's split tier
  (app + worker share one DB), which SQLite cannot back. Provision a SEPARATE staging Postgres
  and pass its URL — never the production one."
case "$DB" in
  postgres://*|postgresql://*) : ;;
  *) die "ACP_STAGING_DATABASE_URL must be a Postgres URL (postgres:// or postgresql://). Got a
  non-Postgres value; SQLite cannot back a split app+worker tier." ;;
esac
[ -n "$REDIS" ] || die "ACP_STAGING_REDIS_URL is required. The split worker tier shares scan/
  remediate tokens through Redis (ADR 0013 §2); without it the API and worker cannot see each
  other's tokens. Provision a staging Redis and pass its URL."

# ── the .NET Office analyser must be built (deploy.sh checks for the DLL, does not build it) ──
say "building the .NET Office analyser (deploy.sh requires the Release DLL)"
DOTNET="${ACP_DOTNET_MUXER:-$(command -v dotnet || echo "$HOME/.dotnet/dotnet")}"
[ -x "$DOTNET" ] || die "no dotnet muxer: tried ACP_DOTNET_MUXER, PATH, and ~/.dotnet/dotnet"
"$DOTNET" build spike/dotnet/AcpScan.Cli -c Release -v quiet --nologo || die "dotnet build failed"

# ── show the plan; a value in the DB URL is never printed (host[:port] only) ──────────────────
_db_host="$(printf '%s' "$DB" | sed -E 's|.*@([^/]*)/.*|\1|')"
SUBNAME="$(az account show ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} --query name -o tsv 2>/dev/null || echo '?')"
# Compute the set/unset display strings explicitly: the `${v:+x}${v:-y}` one-liner would print the
# variable's VALUE in the set case (`:-` yields the value, not ""), leaking the client id / key.
if [ -n "${ACP_STAGING_GOOGLE_CLIENT_ID:-}" ]; then _auth="per-user GIS sign-in"; else _auth="passcode gate (an access code will be minted)"; fi
if [ -n "${ACP_STAGING_LANGFUSE_SECRET_KEY:-}" ]; then _lf="enabled"; else _lf="inherited from existing app, or none"; fi
cat <<PLAN

  Staging provision plan
  ──────────────────────
  subscription : $SUBNAME
  resource grp : ${ACP_RG:-mdk-accessibility}
  app          : $APP_NAME        (external ingress)
  worker       : $WORKER_NAME     (no ingress, drains the job queue)
  database     : Postgres @ $_db_host   (SEPARATE from production)
  redis        : set (cross-replica scan tokens)
  auth         : $_auth
  langfuse     : $_lf

PLAN
if [ -t 0 ] && [ "${ACP_STAGING_YES:-0}" != 1 ]; then
  printf '  Ctrl-C within 5s to abort '
  for _ in 1 2 3 4 5; do printf '.'; sleep 1; done
  printf ' proceeding\n'
fi

# ── hand off to deploy.sh with staging-only env ──────────────────────────────────────────────
# ACP_DEPLOY_WORKER=1 brings up the worker tier FIRST, then flips the API to ACP_WORKERS=0
# (deploy.sh ADR 0013 §2). Only ACP_STAGING_* values are mapped in; nothing else from this shell
# reaches deploy.sh's DATABASE_URL / REDIS_URL / LANGFUSE_* reads.
say "handing off to deploy.sh (this builds the image in ACR and creates both staging apps)"
# Build the mapped environment as an array so only ACP_STAGING_* (+ subscription) reach deploy.sh,
# and any prod DATABASE_URL/REDIS_URL/LANGFUSE_* exported in this shell are explicitly unset. The
# optional entries append only when their source var is set, so an unset one passes nothing rather
# than an empty override deploy.sh would misread.
DEPLOY_ENV=(
  ACP_APP="$APP_NAME"
  ACP_WORKER="$WORKER_NAME"
  ACP_DEPLOY_WORKER=1
  ACP_DATABASE_URL="$DB"
  REDIS_URL="$REDIS"
)
[ -n "${ACP_SUBSCRIPTION:-}" ]               && DEPLOY_ENV+=(ACP_SUBSCRIPTION="$ACP_SUBSCRIPTION")
[ -n "${ACP_STAGING_ACCESS_CODE:-}" ]        && DEPLOY_ENV+=(ACP_ACCESS_CODE="$ACP_STAGING_ACCESS_CODE")
[ -n "${ACP_STAGING_GOOGLE_CLIENT_ID:-}" ]   && DEPLOY_ENV+=(ACP_GOOGLE_CLIENT_ID="$ACP_STAGING_GOOGLE_CLIENT_ID")
[ -n "${ACP_STAGING_LANGFUSE_SECRET_KEY:-}" ] && DEPLOY_ENV+=(LANGFUSE_SECRET_KEY="$ACP_STAGING_LANGFUSE_SECRET_KEY")
[ -n "${ACP_STAGING_LANGFUSE_PUBLIC_KEY:-}" ] && DEPLOY_ENV+=(LANGFUSE_PUBLIC_KEY="$ACP_STAGING_LANGFUSE_PUBLIC_KEY")
env -u DATABASE_URL -u REDIS_URL -u LANGFUSE_SECRET_KEY -u LANGFUSE_PUBLIC_KEY -u ACP_ACCESS_CODE \
  "${DEPLOY_ENV[@]}" bash deploy/public/deploy.sh

# deploy.sh stamps ACP_DEPLOY_ENV=production on every app it creates. That makes IS_PROD true,
# which blocks TEST_BYPASS_ENABLED even when ACP_ENABLE_TEST_BYPASS=true is later set. Staging
# must not be IS_PROD — override it immediately after deploy.sh so subsequent redeploy.sh runs
# (which preserve all env vars) carry "staging" for the life of this environment.
say "overriding ACP_DEPLOY_ENV=staging (deploy.sh stamps 'production'; staging must not be IS_PROD)"
for _app in "$APP_NAME" "$WORKER_NAME"; do
  az containerapp update ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} \
    -g "${ACP_RG:-mdk-accessibility}" -n "$_app" \
    --set-env-vars "ACP_DEPLOY_ENV=staging" -o none
done

# ── tell the operator the one manual step left: flip the workflow on ─────────────────────────
FQDN="$(az containerapp show ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} \
          -g "${ACP_RG:-mdk-accessibility}" -n "$APP_NAME" \
          --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
say "staging is up"
if [ -n "$FQDN" ]; then
  cat <<NEXT
  Staging URL : https://$FQDN

  ONE step left — set the repo variable that un-dormants deploy-staging.yml, so every green
  main starts auto-deploying here:

      gh variable set STAGING_FQDN --body "$FQDN"

  (Optional overrides if you renamed the apps: STAGING_APP / STAGING_WORKER / STAGING_RG.)
  From then on the workflow needs no approval — a \`staging\` GitHub Environment with no reviewers
  is created on its first run.
NEXT
else
  echo "  could not read $APP_NAME's FQDN — check the deploy output above, then set STAGING_FQDN by hand."
fi
