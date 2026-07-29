#!/usr/bin/env bash
# Redeploy acp to Azure — the FAST path, and the only correct one for an app already running.
#
#   deploy.sh   = FIRST deploy. Re-derives all environment: mints a new access code, blanks
#                 DATABASE_URL back to SQLite, drops most of 27 env vars + 9 secrets.
#   redeploy.sh = THIS. Image only. Every env var and secret survives untouched.
#
# Running deploy.sh against a live app is the mistake this script exists to make unnecessary.
#
# WHAT MAKES IT FAST (measured 2026-07-29: 6/6 ACR builds took 2m46s-3m14s, ~3 min each,
# of which the app's own source is seconds):
#
#   1. The expensive layers are pinned base images keyed on a DEPENDENCY hash — the apt block
#      (LibreOffice + a downloaded .NET 10 runtime), pip install, and npm install. `az acr build`
#      has no --cache-from (checked, az 2.86.0), so a QuickRun cannot reuse layers and was
#      re-running all of that for a one-line CSS change. Bases rebuild only when the hash moves.
#   2. acp-app and acp-worker are updated CONCURRENTLY (--no-wait, then poll). Sequential
#      updates also left a window where the two ran DIFFERENT images; they must move together
#      (same image, different entrypoint — scanning happens in the worker).
#
# Guards, all of which are scar tissue from 2026-07-29 (see docs/pipeline.md):
#   - pin to a sha and refuse to build from a dirty or shared tree
#   - vendored worker-python module-count guard (an expired token made it a silent 0-module no-op)
#   - health check BEFORE, so "it was already broken" is distinguishable from "I broke it"
#   - the build args that stamp the CalVer are non-optional; an unstamped image is rejected
#     rather than quietly serving version "dev"
set -euo pipefail

RG="${ACP_RG:-mdk-accessibility}"
ACR="${ACP_ACR:-mdkaccessibilityacr}"
APP="${ACP_APP:-acp-app}"
WORKER="${ACP_WORKER:-acp-worker}"
BUILD_TZ="${BUILD_TZ:-America/Los_Angeles}"
WP="${ACP_PDF_ENGINE_SRC:-$HOME/projects/_review-digital-accessibility/worker-python}"
MIN_MODULES=41
DRY="${ACP_DRY_RUN:-0}"

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── subscription: resolved per-call, never via `az account set` ────────────────────────────
# `az account set` writes a global choice another concurrent process can change mid-deploy.
SUB="$(az account show ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} --query id -o tsv 2>/dev/null || true)"
[ -n "$SUB" ] || die "no active Azure subscription — run 'az login', or set ACP_SUBSCRIPTION"
AZ=(--subscription "$SUB")

# ── 1. pin ─────────────────────────────────────────────────────────────────────────────────
SRC_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$SRC_ROOT"
git fetch -q origin
PIN="${ACP_PIN:-$(git rev-parse origin/main)}"
say "pinning ${PIN:0:7}"

# ── 2. isolated clone ──────────────────────────────────────────────────────────────────────
# `az acr build` uploads the working directory as build context. This repo is worked by many
# concurrent sessions; on 2026-07-29 seventeen files were uncommitted and would have been baked
# into the image. Never build from the shared checkout.
WORK="$(mktemp -d -t acp-deploy-XXXX)"
trap 'rm -rf "$WORK"' EXIT
git clone -q --local "$SRC_ROOT" "$WORK/acp"
cd "$WORK/acp"
git checkout -q "$PIN"

# ── 3. compiled engines ────────────────────────────────────────────────────────────────────
say "building the .NET Office analyser"
"${ACP_DOTNET_MUXER:-$HOME/.dotnet/dotnet}" build spike/dotnet/AcpScan.Cli -c Release -v quiet --nologo \
  || die "dotnet build failed"
[ -f spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll ] \
  || die "AcpScan.Cli.dll missing after a 'successful' build"

say "vendoring the Python PDF analyser"
# Two sources, in order of authority. The engine is NOT in this repo and deploy/public/vendor/
# is gitignored (0 files tracked), so the isolated clone from step 2 never carries it — it has
# to be copied in from outside the clone, every time.
#   1. ACP_PDF_ENGINE_SRC — the real upstream checkout. Authoritative when present.
#   2. the vendored copy already sitting in the source tree, left by a previous deploy. Not
#      authoritative (it is a snapshot, and nothing tells us how old), but it is a real engine
#      and refusing to deploy without the upstream checkout would strand anyone who lacks it.
VENDOR_FROM=""
if [ -d "$WP" ]; then
  VENDOR_FROM="$WP"
elif [ -d "$SRC_ROOT/deploy/public/vendor/worker-python" ]; then
  VENDOR_FROM="$SRC_ROOT/deploy/public/vendor/worker-python"
  echo "  ⚠ ACP_PDF_ENGINE_SRC not found ($WP)"
  echo "  ⚠ falling back to the previously-vendored copy in the source tree — a SNAPSHOT of"
  echo "    unknown age. Set ACP_PDF_ENGINE_SRC to build from the real engine checkout."
else
  die "no PDF engine source: set ACP_PDF_ENGINE_SRC (tried '$WP', and no vendored copy in the source tree)"
fi
mkdir -p deploy/public/vendor
rm -rf deploy/public/vendor/worker-python
cp -R "$VENDOR_FROM" deploy/public/vendor/worker-python
N_MOD="$(find deploy/public/vendor/worker-python -name '*.py' | wc -l | tr -d ' ')"
# An expired ACR token once made this step a silent no-op. 0 modules still BUILDS, and ships an
# empty PDF engine that fails only at runtime, on a customer's document.
[ "$N_MOD" -ge "$MIN_MODULES" ] || die "vendored only $N_MOD modules, expected >= $MIN_MODULES"
echo "  $N_MOD modules"

# ── 4. CalVer ──────────────────────────────────────────────────────────────────────────────
# YYYY.M.D.N in Pacific, N = the count of revisions already created today + 1. Baked into the
# image as ACP_BUILD_VERSION (Dockerfile ARG -> ENV), which is why an image-only update still
# moves the version the UI and /healthz report.
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
read -r BUILD_DATE DAY_START_UTC DAY_SECS <<<"$(python3 - "$BUILD_TIME" "$BUILD_TZ" <<'PY'
import sys, datetime, zoneinfo
t = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
tz = zoneinfo.ZoneInfo(sys.argv[2]); loc = t.astimezone(tz)
start = loc.replace(hour=0, minute=0, second=0, microsecond=0)
print(f"{loc.year}.{loc.month}.{loc.day}",
      start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      int((loc - start).total_seconds()))
PY
)"
# `--all` is REQUIRED: the app runs in Single revision mode, where `revision list` returns only
# the ACTIVE revision, so the count would always be 1 and every deploy would stamp .1.
REV_TIMES="$(az containerapp revision list "${AZ[@]}" -n "$APP" -g "$RG" --all \
              --query "[].properties.createdTime" -o tsv 2>/dev/null || true)"
# Compare only the first 19 chars, exactly as deploy.sh does. createdTime is "…T07:00:00+00:00"
# while the cutoff is "…T07:00:00Z"; a full-string compare differs at char 20, where '+' sorts
# BELOW 'Z', so a revision created precisely at Pacific midnight would be dropped. Both scripts
# must agree — two ordinals for one day is worse than either scheme alone.
SEQ="$(printf '%s\n' "$REV_TIMES" \
       | awk -v cutoff="${DAY_START_UTC:0:19}" 'length($0) >= 19 && substr($0,1,19) >= cutoff' \
       | wc -l | tr -d ' ')"
BUILD_VERSION="${BUILD_DATE}.$(( SEQ + 1 ))"
# Fallback: seconds since Pacific midnight — monotonic within the day and independent of Azure,
# so a throttled revision query never stamps a duplicate ordinal.
[ -n "$REV_TIMES" ] || BUILD_VERSION="${BUILD_DATE}.${DAY_SECS}"
say "CalVer $BUILD_VERSION  (built $BUILD_TIME)"

# ── 5. bases, rebuilt only when their inputs change ────────────────────────────────────────
# The hash covers exactly what the base images are built FROM. Source files are deliberately
# absent: if a source change moved this hash, the cache would never hit and the whole exercise
# would be pointless. Dockerfile.base-* are included so editing the apt block busts the base.
_hash() { cat "$@" | shasum -a 256 | cut -c1-12; }
WEB_HASH="$(_hash frontend/package-lock.json deploy/public/Dockerfile.base-web)"
API_HASH="$(_hash api/requirements.txt deploy/public/Dockerfile.base-api)"
BASE_WEB="$ACR.azurecr.io/acp-base-web:$WEB_HASH"
BASE_API="$ACR.azurecr.io/acp-base-api:$API_HASH"

have_tag() { az acr repository show-tags "${AZ[@]}" -n "$ACR" --repository "$1" -o tsv 2>/dev/null | grep -qx "$2"; }

build_base() {  # repo tag dockerfile
  if have_tag "$1" "$2"; then echo "  ✓ $1:$2 already in the registry — skipping"; return; fi
  say "base $1:$2 is new — building it (this is the slow one, and it is why the app build is not)"
  [ "$DRY" = 1 ] || az acr build "${AZ[@]}" -r "$ACR" -t "$1:$2" -f "$3" . >/dev/null
}
build_base acp-base-web "$WEB_HASH" deploy/public/Dockerfile.base-web
build_base acp-base-api "$API_HASH" deploy/public/Dockerfile.base-api

# ── 6. app image ───────────────────────────────────────────────────────────────────────────
IMG="$ACR.azurecr.io/acp-app:${PIN:0:7}-$(date +%s)"
say "building $IMG"
if [ "$DRY" = 1 ]; then
  echo "  DRY RUN — would build FROM $BASE_WEB / $BASE_API"
else
  az acr build "${AZ[@]}" -r "$ACR" -t "${IMG#*/}" -f deploy/public/Dockerfile \
    --build-arg "BASE_WEB=$BASE_WEB" --build-arg "BASE_API=$BASE_API" \
    --build-arg "BUILD_VERSION=$BUILD_VERSION" --build-arg "BUILD_TIME=$BUILD_TIME" . >/dev/null
fi

# ── 7. health BEFORE ───────────────────────────────────────────────────────────────────────
FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
BEFORE="$(curl -s --max-time 20 "https://$FQDN/healthz" || echo '{}')"
say "before: $BEFORE"
# Both apps must already be running, or a 404 afterwards is unattributable — on 2026-07-29 both
# turned out to have been Stopped before the deploy that appeared to break them.
for a in "$APP" "$WORKER"; do
  st="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$a" --query properties.runningStatus -o tsv)"
  [ "$st" = "Running" ] || die "$a is '$st' before we started — fix that first, do not deploy onto it"
done

[ "$DRY" = 1 ] && { say "DRY RUN — stopping before the update"; exit 0; }

# ── 8. update BOTH, concurrently ───────────────────────────────────────────────────────────
# Same image, different entrypoint. Scanning happens in the worker, so updating only the app
# ships the fixes nowhere useful. --no-wait so the two revisions provision in parallel and the
# window where they run different images is as short as it can be.
say "updating $APP + $WORKER concurrently"
az containerapp update "${AZ[@]}" -g "$RG" -n "$APP"    --image "$IMG" --no-wait >/dev/null
az containerapp update "${AZ[@]}" -g "$RG" -n "$WORKER" --image "$IMG" --no-wait >/dev/null

for a in "$APP" "$WORKER"; do
  printf '  %s ' "$a"
  for _ in $(seq 1 60); do
    img="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$a" --query properties.template.containers[0].image -o tsv 2>/dev/null || true)"
    [ "$img" = "$IMG" ] && { printf ' ✓\n'; break; }
    printf '.'; sleep 5
  done
done

# ── 9. verify ──────────────────────────────────────────────────────────────────────────────
say "verifying"
for _ in $(seq 1 40); do
  AFTER="$(curl -s --max-time 20 "https://$FQDN/healthz" || echo '{}')"
  case "$AFTER" in *"\"version\":\"$BUILD_VERSION\""*) break ;; esac
  sleep 5
done
echo "  after:  $AFTER"
curl -s --max-time 20 "https://$FQDN/readyz" | head -c 400; echo

# The CalVer must have actually moved. An image built without the build args reports "dev" and
# version_stamped:false — it would run perfectly well while every surface lied about what it is.
case "$AFTER" in
  *'"version_stamped":true'*) ;;
  *) die "deployed image is not stamped — it will serve version 'dev'. Build args were lost." ;;
esac
case "$AFTER" in
  *"\"version\":\"$BUILD_VERSION\""*) printf '\n\033[32m✓ %s is live on %s\033[0m\n' "$BUILD_VERSION" "$APP" ;;
  *) die "expected version $BUILD_VERSION, got: $AFTER" ;;
esac
