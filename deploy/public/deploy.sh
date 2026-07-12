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
REDIS_URL="${REDIS_URL:-}"              # set => cross-replica scan-token durability; REQUIRED once the worker tier is split off (ACP_DEPLOY_WORKER=1, ADR 0013 §2)
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
# $ACP_ENV is ambiguous and must not be honoured. It named the Container Apps environment here,
# and api/core.py reads the same name to mean the *deployment* environment (IS_PROD).
# docs/production-hardening.md told operators to `export ACP_ENV=production` as step 1 -- which
# this script read as an ACA environment name, and which never reached the container at all. So
# IS_PROD stayed false on the public demo and the X-E2E-Key bypass stayed live, while standup.sh
# would have CREATED an empty ACA environment called "production". Refuse rather than guess which
# meaning was intended. Checked before anything else: it needs no Azure, and a failing `az` must
# not mask it.
if [ -n "${ACP_ENV:-}" ]; then
  cat >&2 <<EOF
refusing to deploy: ACP_ENV is set ('$ACP_ENV'), and that name is ambiguous.
  - to name the Container Apps environment:  export ACP_ACA_ENV=<aca-env-name>
  - to mark the app as production:           export ACP_DEPLOY_ENV=production
    (this script already stamps ACP_DEPLOY_ENV=production on the container)
EOF
  exit 1
fi
# Resolve the subscription ONCE, then pass it explicitly to every `az` call below via "${AZ[@]}".
#
# This used to be `az account set --subscription`, which writes the choice into
# ~/.azure/azureProfile.json -- a GLOBAL default shared by every shell, every CI step and every
# concurrent agent on this machine. That produced failures in both directions:
#   1. another process ran `az account set` midway through a deploy; this script built and
#      pushed the image, then died at "3/5 registry creds" with "The resource with name
#      'mdkaccessibilityacr' ... could not be found in subscription <someone else's>";
#   2. conversely, a plain `bash deploy.sh` silently repointed the operator's own shell at the
#      demo subscription and left it there after the script exited.
# `--subscription` is per-invocation, so neither can happen. We also pin the immutable
# subscription ID rather than the name, so a rename cannot retarget a running deploy.
if [ -n "${ACP_SUBSCRIPTION:-}" ]; then
  SUB="$(az account show --subscription "$ACP_SUBSCRIPTION" --query id -o tsv 2>/dev/null || true)"
  [ -n "$SUB" ] || { echo "refusing to deploy: ACP_SUBSCRIPTION='$ACP_SUBSCRIPTION' does not resolve to a subscription you can see (az login?)" >&2; exit 1; }
else
  SUB="$(az account show --query id -o tsv 2>/dev/null || true)"
  [ -n "$SUB" ] || { echo "refusing to deploy: no active Azure subscription -- run 'az login', or set ACP_SUBSCRIPTION" >&2; exit 1; }
fi
AZ=(--subscription "$SUB")   # splice into EVERY az call: az foo "${AZ[@]}" ...
echo "   subscription = $(az account show "${AZ[@]}" --query name -o tsv 2>/dev/null || echo '?') ($SUB)"
# Inherit ACP_GOOGLE_CLIENT_ID from the existing ACA if not provided locally, so a plain
# redeploy doesn't accidentally clear or overwrite the already-configured OAuth client id.
if [ -z "$CLIENT_ID" ] && az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" -o none 2>/dev/null; then
  CLIENT_ID="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='ACP_GOOGLE_CLIENT_ID'].value | [0]" \
    -o tsv 2>/dev/null || echo "")"
  [ -n "$CLIENT_ID" ] && echo "   client_id = inherited from existing deployment ($CLIENT_ID)"
fi
[ -f "$ADC_FILE" ] || { echo "no Drive ADC at $ADC_FILE — run: gcloud auth application-default login ..."; exit 1; }
RELEASE="spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll"
[ -f "$RELEASE" ] || { echo "missing .NET Office CLI at $RELEASE — build it first (dotnet build -c Release)"; exit 1; }
# The Container Apps environment NAME, from $ACP_ACA_ENV (see the ACP_ENV guard in preflight).
ENVNAME="${ACP_ACA_ENV:-$(az containerapp env list "${AZ[@]}" -g "$RG" --query '[0].name' -o tsv)}"
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
# ONE timestamp is the single source of truth for BUILD_TIME and, via BUILD_TZ below, for the
# version's date, its day boundary and the fallback ordinal. Two separate `date` calls could
# straddle midnight and stamp tomorrow's date with today's time-of-day.
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Build ordinal (.N) — the number of DEPLOYS today, not commits: the count of acp-app
# revisions already created this PACIFIC day, plus one. Readable (v2026.7.9.5) and monotonic.
#
# It must not be derived from git. The original ordinal counted commits whose UTC committer
# date was today AND that were reachable from HEAD, which had two observed defects:
#   1. it went BACKWARDS on the same day when a deploy ran from a branch behind main
#      (main was live at .28 while a deploy from a stale base stamped .26);
#   2. two rebuilds of the same commit produced the same version, so a redeploy was
#      indistinguishable from the build it replaced.
# Counting revisions has neither problem: every deploy creates exactly one revision, whatever
# branch it came from, so the ordinal only ever increases and a rebuild gets a fresh number.
#
# Known race: two deploys computing N before either has created its revision get the same N.
# The image TAG carries a timestamp so the images stay distinct; only the display version
# collides. With several sessions deploying at once, prefer the later `built_at`.
#
# Known limit: ACA keeps maxInactiveRevisions (100) inactive revisions. More than ~100 deploys
# in one day would prune the day's earliest revisions and the ordinal could repeat. At that
# volume the timestamp fallback below is the better ordinal.
#
# The version's DATE is the calendar day in Pacific time, not UTC. The team and the customer
# are both US/Pacific: a build at 8:06 PM PDT on Jul 9 was stamped "2026.7.10" because UTC had
# already rolled over, and everyone reading it — on a login screen that renders the build
# instant in their own zone, right next to it — saw a version dated tomorrow.
#
# BUILD_TIME stays UTC. It is an instant, and an instant should not carry an offset nobody
# reads. Only the human-facing date+ordinal is localised. Override with BUILD_TZ for a team
# in another zone; the value is any IANA name, and DST is handled (PDT vs PST) by zoneinfo.
BUILD_TZ="${BUILD_TZ:-America/Los_Angeles}"
command -v python3 >/dev/null || { echo "python3 required to compute the build date" >&2; exit 1; }
# Derived from the SAME instant as BUILD_TIME, so the date, the day boundary and the fallback
# ordinal can never straddle midnight relative to one another.
#   1: BUILD_DATE      YYYY.M.D in BUILD_TZ, month/day unpadded
#   2: DAY_START_UTC   that Pacific day's 00:00, expressed in UTC — the ordinal's cutoff
#   3: DAY_SECS        seconds elapsed since Pacific midnight — the fallback ordinal
_CAL="$(python3 - "$BUILD_TIME" "$BUILD_TZ" <<'PY'
import datetime as dt, sys
from zoneinfo import ZoneInfo
inst = dt.datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
loc = inst.astimezone(ZoneInfo(sys.argv[2]))
mid = loc.replace(hour=0, minute=0, second=0, microsecond=0)
print(f"{loc.year}.{loc.month}.{loc.day}")
print(mid.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
print(int((loc - mid).total_seconds()))
PY
)"
BUILD_DATE="$(printf '%s\n' "$_CAL" | sed -n 1p)"
DAY_START_UTC="$(printf '%s\n' "$_CAL" | sed -n 2p)"
DAY_SECS="$(printf '%s\n' "$_CAL" | sed -n 3p)"
# `--all` is REQUIRED: the app runs in Single revision mode, where `revision list` returns
# only the ACTIVE revision. Without it the count is always 1 and every deploy stamps .1.
# `|| true`: the app may not exist yet (first deploy), which would kill the script under
# `set -euo pipefail` before the fallback runs.
REV_TIMES="$(az containerapp revision list "${AZ[@]}" -n "$APP" -g "$RG" --all \
              --query "[].properties.createdTime" -o tsv 2>/dev/null || true)"
# Count revisions created at or after Pacific midnight. A UTC-date prefix match cannot express
# that boundary — at 8 PM PDT the Pacific day holds revisions from two different UTC days.
# createdTime is UTC ISO ("2026-07-10T03:09:09+00:00"), so the first 19 chars are fixed-width
# and sort chronologically; comparing them to the cutoff's first 19 avoids Z vs +00:00.
BUILD_SEQ="$(printf '%s\n' "$REV_TIMES" \
             | awk -v cutoff="${DAY_START_UTC:0:19}" 'length($0) >= 19 && substr($0,1,19) >= cutoff' \
             | wc -l | tr -d ' ')"
BUILD_SEQ=$(( BUILD_SEQ + 1 ))
# Fallback: seconds since Pacific midnight. Still monotonic within the day, and independent of
# both git and Azure, so a throttled/failed revision query never stamps a duplicate .1.
if [ -z "$REV_TIMES" ]; then
  BUILD_SEQ="$DAY_SECS"
  echo "   (revision query returned nothing — ordinal falls back to seconds-since-midnight)"
fi
BUILD_VERSION="${BUILD_DATE}.${BUILD_SEQ}"
# Refuse to ship an unstamped image. The Dockerfile falls back to ARG BUILD_VERSION=dev,
# which is right for a local `docker build` but must never reach the demo: a "dev" version
# in /healthz makes a rollout unattributable. Fail here rather than after the image is
# built and pushed. (The app enforces the other half: /healthz reports ok=false for an
# unstamped image, see api/routes/system.py:_build_info.)
# The ordinal is 1..6 digits: a small deploy count (.6) normally, or seconds-since-midnight
# (.4187) on the fallback path. Pinning it to exactly 6 digits would reject every real stamp
# this script now produces — the guard exists to catch an UNSTAMPED image, not to police the
# ordinal's width.
if ! [[ "$BUILD_VERSION" =~ ^[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,6}$ ]]; then
  echo "refusing to deploy: BUILD_VERSION '$BUILD_VERSION' is not a CalVer stamp (YYYY.M.D.N)" >&2
  exit 1
fi
echo "   version $BUILD_VERSION · built $BUILD_TIME"
az acr build "${AZ[@]}" -r "$ACR" -t "$IMAGE" -f deploy/public/Dockerfile \
  --build-arg BUILD_VERSION="$BUILD_VERSION" --build-arg BUILD_TIME="$BUILD_TIME" . -o none

echo "== 3/5 registry creds =="
ACRSERVER="$(az acr show "${AZ[@]}" -n "$ACR" --query loginServer -o tsv)"
ACRUSER="$(az acr credential show "${AZ[@]}" -n "$ACR" --query username -o tsv)"
ACRPW="$(az acr credential show "${AZ[@]}" -n "$ACR" --query 'passwords[0].value' -o tsv)"

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
  EXISTING_DB="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
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
  EXISTING_LF_SK="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='LANGFUSE_SECRET_KEY'].secretRef | [0]" -o tsv 2>/dev/null || echo "")"
  EXISTING_LF_PK="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='LANGFUSE_PUBLIC_KEY'].secretRef | [0]" -o tsv 2>/dev/null || echo "")"
  EXISTING_LF_HOST="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
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
  EXISTING_DEMO_KEY="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
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
  EXISTING_E2E="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='ACP_E2E_KEY'].secretRef | [0]" \
    -o tsv 2>/dev/null || echo "")"
  E2E_ENV="${EXISTING_E2E:+ACP_E2E_KEY=secretref:$EXISTING_E2E}"
  echo "   e2e key = inherited"
fi
# Redis — cross-replica scan-token durability (core.register_scan_tokens / get_scan_tokens).
# Harmless when absent on the single-container default (tokens fall back to per-process memory),
# but REQUIRED once the worker tier is split off: a separate worker process can't see the
# in-memory tokens the API registered. Inherit on a bare redeploy so it isn't dropped.
if [ -n "$REDIS_URL" ]; then
  SECRETS+=("redis-url=$REDIS_URL")
  REDIS_ENV="REDIS_URL=secretref:redis-url"
  echo "   redis = set (cross-replica scan tokens)"
else
  EXISTING_REDIS="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='REDIS_URL'].secretRef | [0]" \
    -o tsv 2>/dev/null || echo "")"
  REDIS_ENV="${EXISTING_REDIS:+REDIS_URL=secretref:$EXISTING_REDIS}"
  echo "   redis = ${EXISTING_REDIS:+inherited}${EXISTING_REDIS:-disabled (single-process tokens)}"
fi
# Async worker pool — ACP_WORKERS=N runs N in-process job workers. Plain (non-secret)
# env vars; inherit when not passed so a bare redeploy keeps them.
_inherit_env() {  # $1 = var name → echoes "NAME=value" if currently set, else ""
  local v; v="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
    --query "properties.template.containers[0].env[?name=='$1'].value | [0]" -o tsv 2>/dev/null || echo "")"
  # `if`, not `[ -n "$v" ] && echo ...`: the && form returns 1 when $v is empty, and the caller
  # assigns it as the LAST command of an && list, so `set -e` aborted the whole deploy whenever
  # the variable was absent. Nothing inherits on a first-ever deploy, so the `containerapp create`
  # path below was unreachable. Absent is a normal outcome here, not an error.
  if [ -n "$v" ]; then echo "$1=$v"; fi
}
WORKERS_ENV="${ACP_WORKERS:+ACP_WORKERS=$ACP_WORKERS}"; [ -z "$WORKERS_ENV" ] && WORKERS_ENV="$(_inherit_env ACP_WORKERS)"
EMAILS_ENV="${ACP_ALLOWED_EMAILS:+ACP_ALLOWED_EMAILS=$ACP_ALLOWED_EMAILS}"; [ -z "$EMAILS_ENV" ] && EMAILS_ENV="$(_inherit_env ACP_ALLOWED_EMAILS)"
BLOB_ENV="ACP_BLOB_ACCOUNT=$BLOB_ACCOUNT"
# This script only ever deploys the public demo, so the app it produces IS production.
# Stamp it so core.IS_PROD is true, which refuses the X-E2E-Key / X-Demo-Key bypasses even
# if someone later sets ACP_ENABLE_TEST_BYPASS on the app. ACP_DEPLOY_ENV is the only name for
# this; the ACA environment name is now ACP_ACA_ENV, and ACP_ENV is refused outright (preflight).
DEPLOY_ENV_ENV="ACP_DEPLOY_ENV=production"
# ADR 0020 stage 4 — Discover lists only; the download + WCAG analysis run at Assess. Default ON.
# Instant revert without a code change:  ACP_DEFER_ANALYSIS_TO_ASSESS=0 bash deploy/public/deploy.sh
DEFER_ENV="ACP_DEFER_ANALYSIS_TO_ASSESS=${ACP_DEFER_ANALYSIS_TO_ASSESS:-1}"
echo "   defer analysis to Assess = ${ACP_DEFER_ANALYSIS_TO_ASSESS:-1} (ADR 0020)"
echo "   deploy env = production (test/demo auth bypasses refused)"
echo "   workers = ${ACP_WORKERS:-${WORKERS_ENV:+inherited}}${WORKERS_ENV:+}"
echo "   allowed emails = ${ACP_ALLOWED_EMAILS:-${EMAILS_ENV:+inherited}}"
echo "   blob account = $BLOB_ACCOUNT"
# ── Optional: split worker tier (ADR 0013 §2) ────────────────────────────────
# ACP_DEPLOY_WORKER=1 stands up (or updates) a separate `acp-worker` Container App that drains
# the job queue via `python -m worker_main` with NO HTTP ingress, then flips the API to
# ACP_WORKERS=0 below so the two tiers scale independently. It reuses the SAME image + secrets
# built above; only the command + a couple of env vars differ (ADR 0013 §2 "code-ready").
#
# Ordering matters (ADR 0013 §2): the worker app is brought up FIRST, here, and the API is
# flipped to ACP_WORKERS=0 only afterwards — never leave the queue with no drainer.
#
# Requires REDIS_URL: once API and workers are different processes the per-process token
# fallback can't share scan/remediate tokens, so refuse without it.
#
# ONE-TIME after the first create: the worker writes remediated output to Blob via managed
# identity, so grant its identity Storage Blob Data Contributor (commands printed below), else
# remediation blob writes 403 from the worker tier.
#
# NOTE: this path is codified but not yet exercised against live infra (it's gated behind the
# billable Redis + second app, greenlit separately) — shake out az-CLI specifics (notably the
# --command quoting) on the first real spin-up.
WORKER_APP="acp-worker"
# Same ADC bootstrap as the API's Dockerfile CMD, but exec the worker entrypoint instead of uvicorn.
WORKER_CMD='if [ -n "$ACP_GOOGLE_ADC" ]; then printf "%s" "$ACP_GOOGLE_ADC" > /tmp/adc.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/adc.json; fi; exec python -m worker_main'
if [ "${ACP_DEPLOY_WORKER:-}" = "1" ]; then
  if [ -z "$REDIS_ENV" ]; then
    echo "refusing: ACP_DEPLOY_WORKER=1 requires REDIS_URL (cross-replica scan tokens, ADR 0013 §2)" >&2
    exit 1
  fi
  WK_N="${ACP_WORKER_COUNT:-2}"
  echo "== worker tier: (re)deploy $WORKER_APP — python -m worker_main, $WK_N workers, no ingress =="
  if az containerapp show "${AZ[@]}" -g "$RG" -n "$WORKER_APP" -o none 2>/dev/null; then
    _retry az containerapp secret set "${AZ[@]}" -g "$RG" -n "$WORKER_APP" --secrets "${SECRETS[@]}" -o none
    _retry az containerapp registry set "${AZ[@]}" -g "$RG" -n "$WORKER_APP" \
      --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
    _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$WORKER_APP" --image "$ACRSERVER/$IMAGE" \
      --command "/bin/sh" "-c" "$WORKER_CMD" \
      --set-env-vars ACP_GOOGLE_ADC=secretref:google-adc $DEPLOY_ENV_ENV $DB_ENV $LF_ENV $DEMO_ENV $BLOB_ENV $REDIS_ENV ACP_WORKERS=$WK_N -o none
  else
    az containerapp create "${AZ[@]}" -g "$RG" -n "$WORKER_APP" --environment "$ENVNAME" \
      --image "$ACRSERVER/$IMAGE" \
      --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
      --command "/bin/sh" "-c" "$WORKER_CMD" \
      --secrets "${SECRETS[@]}" \
      --env-vars ACP_GOOGLE_ADC=secretref:google-adc $DEPLOY_ENV_ENV $DB_ENV $LF_ENV $DEMO_ENV $BLOB_ENV $REDIS_ENV ACP_WORKERS=$WK_N \
      --system-assigned --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 3 -o none
    echo "   one-time: grant the worker's managed identity 'Storage Blob Data Contributor' on"
    echo "   the '$BLOB_ACCOUNT' account so its remediation Blob writes don't 403 — exact"
    echo "   commands are in docs/adr/0013-worker-durability-hardening.md (§2 runbook)."
  fi
  # ADR 0013 §2: hand job processing to the worker tier — flip the API to serve-only.
  WORKERS_ENV="ACP_WORKERS=0"
  echo "   API → ACP_WORKERS=0 (job processing handed to $WORKER_APP)"
fi

if az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" -o none 2>/dev/null; then
  _retry az containerapp secret set "${AZ[@]}" -g "$RG" -n "$APP" \
    --secrets "${SECRETS[@]}" -o none
  _retry az containerapp registry set "${AZ[@]}" -g "$RG" -n "$APP" \
    --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
  _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" --image "$ACRSERVER/$IMAGE" \
    --set-env-vars ACP_GOOGLE_ADC=secretref:google-adc $DEPLOY_ENV_ENV $DEFER_ENV $MODE_ENV $DB_ENV $LF_ENV $HITL_ENV $DEMO_ENV $E2E_ENV $WORKERS_ENV $EMAILS_ENV $BLOB_ENV $REDIS_ENV -o none
else
  az containerapp create "${AZ[@]}" -g "$RG" -n "$APP" --environment "$ENVNAME" \
    --image "$ACRSERVER/$IMAGE" \
    --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
    --target-port 8077 --ingress external \
    --secrets "${SECRETS[@]}" \
    --env-vars ACP_GOOGLE_ADC=secretref:google-adc $DEPLOY_ENV_ENV $DEFER_ENV $MODE_ENV $DB_ENV $LF_ENV $HITL_ENV $DEMO_ENV $E2E_ENV $WORKERS_ENV $EMAILS_ENV $BLOB_ENV $REDIS_ENV \
    --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 1 -o none
fi

echo "== 5/5 done =="
FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"

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
  az acr build "${AZ[@]}" -r "$ACR" -t "$GF_IMAGE" -f deploy/grafana/Dockerfile deploy/grafana -o none
  if az containerapp show "${AZ[@]}" -g "$RG" -n "$GF_APP" -o none 2>/dev/null; then
    # Ensure the Grafana app can pull from the private ACR before updating its
    # image (an older acp-grafana may have been created without these creds,
    # which fails the revision with UNAUTHORIZED).
    _retry az containerapp registry set "${AZ[@]}" -g "$RG" -n "$GF_APP" \
      --server "$ACRSERVER" --username "$ACRUSER" --password "$ACRPW" -o none
    _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$GF_APP" --image "$ACRSERVER/$GF_IMAGE" \
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
    az containerapp create "${AZ[@]}" -g "$RG" -n "$GF_APP" --environment "$ENVNAME" \
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
  GF_FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$GF_APP" --query properties.configuration.ingress.fqdn -o tsv)"
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
