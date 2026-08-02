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
MIN_MODULES=41                  # engine/pdf-analyser is tracked; this guards against truncation
DRY="${ACP_DRY_RUN:-0}"
BG="${ACP_BLUE_GREEN:-0}"       # 1 => green provisions at 0% traffic, is tested, then promoted

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

# The CI gate, ENFORCED rather than described. This step's own comment has always said "check CI
# is green on it", and nothing ever checked — a human was expected to remember. Deploying an
# unbuilt commit is exactly the mistake an automated pipeline makes faster than a person.
#
# Skipped, loudly, when gh is unavailable or unauthenticated: a local operator without gh should
# still be able to ship, and a gate that silently passes is worse than one that says it was not
# run. ACP_SKIP_CI_GATE=1 is the deliberate override for a commit CI cannot see (a local-only pin).
if [ "${ACP_SKIP_CI_GATE:-0}" = 1 ]; then
  echo "  ⚠ CI gate SKIPPED by ACP_SKIP_CI_GATE=1"
elif ! command -v gh >/dev/null 2>&1; then
  echo "  ⚠ CI gate NOT CHECKED — gh is not installed on this host"
elif ! gh auth status >/dev/null 2>&1; then
  echo "  ⚠ CI gate NOT CHECKED — gh is not authenticated"
else
  CI_CONC="$(gh run list --commit "$PIN" --workflow CI --limit 1 --json conclusion -q '.[0].conclusion' 2>/dev/null || true)"
  case "$CI_CONC" in
    success) echo "  ✓ CI is green on ${PIN:0:7}" ;;
    "")      die "no CI run found for ${PIN:0:7} — it may still be queued. Wait for it, or set ACP_SKIP_CI_GATE=1 if this pin is deliberately not on a branch CI builds." ;;
    *)       die "CI on ${PIN:0:7} concluded '$CI_CONC', not success — refusing to deploy it." ;;
  esac
fi

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
# Resolve dotnet the same way api/scanner.py and tests/engines.py do: explicit override, then
# PATH, then the dev-machine install location. PATH is what makes this work on a CI runner —
# actions/setup-dotnet puts the muxer on PATH and never creates ~/.dotnet/dotnet, so the old
# hard-coded default would have failed on the very host CD runs on.
DOTNET="${ACP_DOTNET_MUXER:-$(command -v dotnet || echo "$HOME/.dotnet/dotnet")}"
[ -x "$DOTNET" ] || die "no dotnet muxer: tried ACP_DOTNET_MUXER, PATH, and ~/.dotnet/dotnet"
"$DOTNET" build spike/dotnet/AcpScan.Cli -c Release -v quiet --nologo \
  || die "dotnet build failed"
[ -f spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll ] \
  || die "AcpScan.Cli.dll missing after a 'successful' build"

say "checking the vendored Python PDF analyser"
# There is no vendoring STEP any more. The engine is tracked at engine/pdf-analyser (ADR 0029),
# so the isolated clone from step 2 already carries it and the build context is complete by
# construction — which is what makes a CI runner able to build this image at all.
#
# The count guard stays, now against the tracked tree. It earned its place: an expired token once
# made the old copy-from-outside step a silent no-op, and 0 modules still BUILDS, shipping an
# image that looks fine and cannot assess a single PDF. A guard that can only fire on a deletion
# is cheap enough to keep.
N_MOD="$(find engine/pdf-analyser -name '*.py' | wc -l | tr -d ' ')"
[ "$N_MOD" -ge "$MIN_MODULES" ] || die "engine/pdf-analyser has only $N_MOD modules, expected >= $MIN_MODULES — the vendored engine looks truncated, refusing to build"
echo "  $N_MOD modules (tracked in-repo)"

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
    --build-arg "BUILD_VERSION=$BUILD_VERSION" --build-arg "BUILD_TIME=$BUILD_TIME" \
    --build-arg "BUILD_SHA=$PIN" . >/dev/null
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

if [ "$DRY" = 1 ]; then
  # A dry run that skipped the blue-green block would leave the riskiest path — the one that
  # moves production traffic — as the only part nobody ever rehearses. So walk it here using
  # READS ONLY, and print the revisions it would actually touch, resolved live.
  if [ "$BG" = 1 ]; then
    ENV_DOMAIN="$(az containerapp env list "${AZ[@]}" -g "$RG" --query '[0].properties.defaultDomain' -o tsv)"
    MODE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.configuration.activeRevisionsMode -o tsv)"
    BLUE="$(az containerapp ingress traffic show "${AZ[@]}" -g "$RG" -n "$APP" \
              --query "[?weight>\`0\`] | [0].revisionName" -o tsv 2>/dev/null || true)"
    [ -n "$BLUE" ] || BLUE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.latestRevisionName -o tsv)"
    SUFFIX="g$(printf '%s' "$BUILD_VERSION" | tr -cd '0-9')"
    say "DRY RUN — blue-green plan"
    echo "  revision mode  : $MODE$([ "$MODE" != Multiple ] && echo '  -> would switch to Multiple')"
    echo "  blue (keeps traffic until promotion): $BLUE"
    echo "  green (would provision at 0%)      : $APP--$SUFFIX"
    echo "  green smoke-test url               : https://$APP--$SUFFIX.$ENV_DOMAIN/healthz"
    echo "  worker cutover                     : $WORKER -> $IMG  (NOT blue-green)"
  fi
  say "DRY RUN — stopping before anything is changed"
  exit 0
fi

# ── 8-BG. blue-green (ACP_BLUE_GREEN=1) ────────────────────────────────────────────────────
#
# WHAT IS AND IS NOT PROTECTED — read this before trusting the word "blue-green".
#
# ACA splits traffic by INGRESS WEIGHT. acp-app has external ingress, so it gets the real thing:
# green provisions at 0%, is smoke-tested on its own FQDN while production still serves blue, and
# takes traffic in one weight change that reverses just as fast.
#
# acp-worker has NO INGRESS (properties.configuration.ingress is null). It takes work by pulling
# from a shared job queue, so a second worker on a different image would pull from that SAME
# queue — blue and green racing over live production jobs, picked at random. There is no weight
# to set and nothing to split. The worker therefore CUTS OVER at promotion, and that step is not
# protected. Saying so is the point; a deploy script that implied otherwise would be worse than
# one that never claimed blue-green at all.
#
# Consequence while green sits at 0%: the system is MIXED — green app on the new image, worker
# still on the old one. Read-only checks are fine. Anything that enqueues a job whose contract
# changed is NOT: green would enqueue work the old worker cannot correctly process. That is why
# the smoke tests below are read-only, and it is a rule rather than an oversight.
#
# Making the worker genuinely blue-green needs queue partitioning — green consumes its own queue,
# promotion swaps which queue the app enqueues to. That is an application change (worker_main.py
# plus the job table), not a deploy-script change, and it is deliberately out of scope here.
if [ "$BG" = 1 ]; then
  ENV_DOMAIN="$(az containerapp env list "${AZ[@]}" -g "$RG" --query '[0].properties.defaultDomain' -o tsv)"

  # Multiple-revision mode, idempotently. Switching Single -> Multiple leaves the running revision
  # on 100%, so it is safe against a live app, and it is a no-op once set.
  MODE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.configuration.activeRevisionsMode -o tsv)"
  if [ "$MODE" != "Multiple" ]; then
    say "switching $APP to multiple-revision mode (currently $MODE)"
    az containerapp revision set-mode "${AZ[@]}" -g "$RG" -n "$APP" --mode multiple >/dev/null
  fi

  # BLUE = whatever holds traffic RIGHT NOW, captured before anything changes. After the update
  # the "latest" revision is green, so blue is no longer reachable by that route.
  BLUE="$(az containerapp ingress traffic show "${AZ[@]}" -g "$RG" -n "$APP" \
            --query "[?weight>\`0\`] | [0].revisionName" -o tsv 2>/dev/null || true)"
  [ -n "$BLUE" ] || BLUE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.latestRevisionName -o tsv)"
  BLUE_IMG="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query properties.template.containers[0].image -o tsv)"
  say "blue = $BLUE"

  # Green at 0%. In Multiple mode weights are explicit, so a new revision takes no traffic until
  # told to — there is no "hold it back" flag to forget.
  SUFFIX="g$(printf '%s' "$BUILD_VERSION" | tr -cd '0-9')"
  GREEN="$APP--$SUFFIX"
  say "deploying green ($GREEN) at 0% traffic"
  az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" --image "$IMG" --revision-suffix "$SUFFIX" >/dev/null

  GREEN_FQDN="$GREEN.$ENV_DOMAIN"
  printf '  waiting for green '
  for _ in $(seq 1 60); do
    case "$(curl -s --max-time 10 "https://$GREEN_FQDN/healthz" || true)" in
      *'"ok":true'*) printf ' ✓\n'; break ;;
    esac
    printf '.'; sleep 5
  done

  # Smoke-test green on its OWN url while production still serves blue. Read-only (see header).
  # Every failure below leaves blue on 100% and exits — a green that cannot prove itself must not
  # take traffic, and the message says so rather than leaving the operator to infer it.
  say "smoke-testing green at $GREEN_FQDN"
  GHZ="$(curl -s --max-time 20 "https://$GREEN_FQDN/healthz" || echo '{}')"
  echo "  healthz: $GHZ"
  case "$GHZ" in
    *'"version_stamped":true'*) ;;
    *) die "green is not stamped — it would serve version 'dev'. NOT promoting; blue still has all traffic." ;;
  esac
  case "$GHZ" in
    *"\"version\":\"$BUILD_VERSION\""*) ;;
    *) die "green reports the wrong version (wanted $BUILD_VERSION). NOT promoting; blue still has all traffic." ;;
  esac
  curl -sf --max-time 20 "https://$GREEN_FQDN/readyz" >/dev/null \
    || die "green /readyz failed. NOT promoting; blue still has all traffic."
  echo "  readyz:  ok"

  say "promoting green to 100%"
  az containerapp ingress traffic set "${AZ[@]}" -g "$RG" -n "$APP" \
    --revision-weight "$GREEN=100" "$BLUE=0" >/dev/null

  say "cutting $WORKER over to the same image (NOT blue-green — see header)"
  az containerapp update "${AZ[@]}" -g "$RG" -n "$WORKER" --image "$IMG" --no-wait >/dev/null
  printf '  %s ' "$WORKER"
  for _ in $(seq 1 60); do
    img="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$WORKER" --query properties.template.containers[0].image -o tsv 2>/dev/null || true)"
    [ "$img" = "$IMG" ] && { printf ' ✓\n'; break; }
    printf '.'; sleep 5
  done

  # Verified through the PUBLIC url, not green's. Green being healthy proves green is healthy;
  # only the public url proves traffic actually moved.
  say "verifying on the public url"
  for _ in $(seq 1 40); do
    AFTER="$(curl -s --max-time 20 "https://$FQDN/healthz" || echo '{}')"
    case "$AFTER" in *"\"version\":\"$BUILD_VERSION\""*) break ;; esac
    sleep 5
  done
  echo "  after: $AFTER"
  case "$AFTER" in
    *"\"version\":\"$BUILD_VERSION\""*) printf '\n\033[32m✓ %s is live on %s (blue %s kept at 0%% for rollback)\033[0m\n' "$BUILD_VERSION" "$APP" "$BLUE" ;;
    *) die "traffic did not move to green. Roll back with the commands below." ;;
  esac

  # Blue stays at 0% rather than being deactivated, so rollback needs no rebuild. Printed with the
  # real names filled in: recovery should be a paste, not a reconstruction under pressure.
  cat <<ROLLBACK

  Rollback — app is instant (a weight change, nothing provisions); the worker needs ~20s:

    az containerapp ingress traffic set -g $RG -n $APP --revision-weight $BLUE=100 $GREEN=0
    az containerapp update -g $RG -n $WORKER --image $BLUE_IMG

  Run BOTH. A new worker under an old app is the mixed-version state promotion exists to close.
ROLLBACK
  exit 0
fi

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
