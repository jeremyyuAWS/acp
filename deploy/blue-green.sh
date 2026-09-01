#!/usr/bin/env bash
# blue-green.sh — cut over acp-app to a pre-built image with zero-downtime traffic splitting.
#
# USAGE
#   ACP_IMG=mdkaccessibilityacr.azurecr.io/acp-app:<tag> ./deploy/blue-green.sh
#
# This script operates on an image that is already in ACR. It does not build anything.
# To build AND deploy in one step, use redeploy.sh with ACP_BLUE_GREEN=1 — it calls the
# same logic after building the image and running pre-deploy guards.
#
# REQUIRED
#   ACP_IMG              Full image reference (ACR login server / repo : tag)
#
# OPTIONAL
#   ACP_RG               Resource group          (default: mdk-accessibility)
#   ACP_APP              App container app name  (default: acp-app)
#   ACP_*_WORKER         Stage worker names      (defaults: acp-discovery/assess/remediate)
#   ACP_SUBSCRIPTION     Azure subscription ID   (default: resolved from az account show)
#   ACP_BUILD_VERSION    CalVer to assert on green /healthz (default: not checked)
#   ACP_REVISION_SUFFIX  Revision name suffix    (default: g<unix-epoch>)
#   ACP_DRY_RUN          1 = read-only preview, no changes (default: 0)
#
# WHAT IS AND IS NOT PROTECTED — read this before trusting the word "blue-green".
#
# acp-app has external ingress. Green provisions at 0%, is smoke-tested on its own per-revision
# FQDN while production still serves blue, and takes traffic in a single weight change that
# reverses just as fast — that is real blue-green.
#
# Stage workers have NO INGRESS. Both revisions pull from the same shared job queue — blue and green
# would race over live production jobs. There is no ingress weight to split. The worker therefore
# cuts over at promotion; that step is not protected by this script. Saying so is the point; a
# script that implied otherwise would be worse than one that never claimed blue-green at all.
#
# Making the worker genuinely blue-green requires queue partitioning (green consumes its own
# queue; promotion swaps which queue the app enqueues to). That is an application change, not
# a deploy-script change, and is deliberately out of scope here.

set -euo pipefail

IMG="${ACP_IMG:?ACP_IMG is required — set it to the full image reference already in ACR}"
RG="${ACP_RG:-mdk-accessibility}"
APP="${ACP_APP:-acp-app}"
DISCOVERY_WORKER="${ACP_DISCOVERY_WORKER:-acp-discovery}"
ASSESS_WORKER="${ACP_ASSESS_WORKER:-acp-assess}"
REMEDIATE_WORKER="${ACP_REMEDIATE_WORKER:-acp-remediate}"
LANE_WORKERS=("$DISCOVERY_WORKER" "$ASSESS_WORKER" "$REMEDIATE_WORKER")
DRY="${ACP_DRY_RUN:-0}"
BUILD_VERSION="${ACP_BUILD_VERSION:-}"

say()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }

# ── Subscription: resolved per-call, never via `az account set` ──────────────
# `az account set` writes a global choice another concurrent process can change mid-deploy.
SUB="$(az account show ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} --query id -o tsv 2>/dev/null || true)"
[ -n "$SUB" ] || die "no active Azure subscription — run 'az login', or set ACP_SUBSCRIPTION"
AZ=(--subscription "$SUB")

# ── Pre-flight: both apps must be Running, public healthz must respond ────────
say "pre-flight"
FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
          --query properties.configuration.ingress.fqdn -o tsv)"
for a in "$APP" "${LANE_WORKERS[@]}"; do
  st="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$a" --query properties.runningStatus -o tsv)"
  [ "$st" = "Running" ] || die "$a is '$st' before we started — fix that first; do not deploy onto a stopped app"
done
BEFORE="$(curl -s --max-time 20 "https://$FQDN/healthz" || echo '{}')"
echo "  current: $BEFORE"

# ── Revision suffix ───────────────────────────────────────────────────────────
SUFFIX="${ACP_REVISION_SUFFIX:-g$(date +%s)}"
GREEN="$APP--$SUFFIX"

# ── Dry-run: read-only preview ────────────────────────────────────────────────
# Walks the blue-green path using reads only so the riskiest logic is actually exercised
# rather than skipped, and prints the real revision names it would touch.
if [ "$DRY" = 1 ]; then
  ENV_DOMAIN="$(az containerapp env list "${AZ[@]}" -g "$RG" \
                  --query '[0].properties.defaultDomain' -o tsv)"
  MODE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
            --query properties.configuration.activeRevisionsMode -o tsv)"
  BLUE="$(az containerapp ingress traffic show "${AZ[@]}" -g "$RG" -n "$APP" \
            --query "[?weight>\`0\`] | [0].revisionName" -o tsv 2>/dev/null || true)"
  [ -n "$BLUE" ] || BLUE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
                               --query properties.latestRevisionName -o tsv)"
  say "DRY RUN — blue-green plan (no changes will be made)"
  echo "  image              : $IMG"
  echo "  revision mode      : $MODE$([ "$MODE" != Multiple ] && echo '  -> would switch to Multiple')"
  echo "  blue (keeps 100%)  : $BLUE"
  echo "  green (at 0%)      : $GREEN"
  echo "  green smoke-test   : https://$GREEN.$ENV_DOMAIN/healthz"
  echo "  worker cutover     : ${LANE_WORKERS[*]} -> $IMG  (not blue-green — no ingress)"
  [ -n "$BUILD_VERSION" ] && echo "  version asserted   : $BUILD_VERSION"
  say "DRY RUN — stopped before any change"
  exit 0
fi

# ── Multiple-revision mode (idempotent) ───────────────────────────────────────
# Switching Single -> Multiple leaves the current revision at 100%, so it is safe against a
# live app, and it is a no-op when already Multiple.
MODE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
          --query properties.configuration.activeRevisionsMode -o tsv)"
if [ "$MODE" != "Multiple" ]; then
  say "switching $APP to multiple-revision mode (currently $MODE)"
  az containerapp revision set-mode "${AZ[@]}" -g "$RG" -n "$APP" --mode multiple >/dev/null
fi

# ── Capture blue ──────────────────────────────────────────────────────────────
# Captured before anything changes — after the update the "latest" revision is green, so blue
# is no longer reachable by that route.
BLUE="$(az containerapp ingress traffic show "${AZ[@]}" -g "$RG" -n "$APP" \
          --query "[?weight>\`0\`] | [0].revisionName" -o tsv 2>/dev/null || true)"
[ -n "$BLUE" ] || BLUE="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
                             --query properties.latestRevisionName -o tsv)"
BLUE_IMG="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
              --query properties.template.containers[0].image -o tsv)"
say "blue = $BLUE"

# ── Deploy green at 0% ────────────────────────────────────────────────────────
# In Multiple mode, weights are explicit — a new revision takes no traffic until told to.
ENV_DOMAIN="$(az containerapp env list "${AZ[@]}" -g "$RG" \
                --query '[0].properties.defaultDomain' -o tsv)"
say "deploying green ($GREEN) at 0% traffic"
az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" \
  --image "$IMG" --revision-suffix "$SUFFIX" >/dev/null

# Poll green's per-revision FQDN until healthz responds ok (up to 5 minutes).
GREEN_FQDN="$GREEN.$ENV_DOMAIN"
printf '  waiting for green '
for _ in $(seq 1 60); do
  case "$(curl -s --max-time 10 "https://$GREEN_FQDN/healthz" || true)" in
    *'"ok":true'*) printf ' ✓\n'; break ;;
  esac
  printf '.'; sleep 5
done

# ── Smoke-test green on its own URL ──────────────────────────────────────────
# Read-only checks only — see header. Any failure exits without touching traffic;
# blue stays at 100% and the message says so explicitly.
say "smoke-testing green at $GREEN_FQDN"
GHZ="$(curl -s --max-time 20 "https://$GREEN_FQDN/healthz" || echo '{}')"
echo "  healthz: $GHZ"

case "$GHZ" in
  *'"ok":true'*) ;;
  *) die "green /healthz did not return ok. Blue still has all traffic. Fix before retrying." ;;
esac
case "$GHZ" in
  *'"version_stamped":true'*) ;;
  *) die "green is not version-stamped (would serve version 'dev'). Blue still has all traffic." ;;
esac
if [ -n "$BUILD_VERSION" ]; then
  case "$GHZ" in
    *"\"version\":\"$BUILD_VERSION\""*) ;;
    *) die "green reports unexpected version (wanted $BUILD_VERSION). Blue still has all traffic." ;;
  esac
fi
curl -sf --max-time 20 "https://$GREEN_FQDN/readyz" >/dev/null \
  || die "green /readyz returned non-200. Blue still has all traffic."
echo "  readyz:  ok"

# ── Promote green to 100% ─────────────────────────────────────────────────────
# Blue stays at 0% (not deactivated) so rollback is a single weight change — no rebuild needed.
say "promoting green to 100%"
az containerapp ingress traffic set "${AZ[@]}" -g "$RG" -n "$APP" \
  --revision-weight "$GREEN=100" "$BLUE=0" >/dev/null

# ── Worker cutover (NOT blue-green — no ingress to split) ────────────────────
say "cutting ${LANE_WORKERS[*]} over to the same image"
for a in "${LANE_WORKERS[@]}"; do
  az containerapp update "${AZ[@]}" -g "$RG" -n "$a" --image "$IMG" --no-wait >/dev/null
done
for a in "${LANE_WORKERS[@]}"; do
  printf '  %s ' "$a"
  for _ in $(seq 1 60); do
    img="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$a" \
             --query properties.template.containers[0].image -o tsv 2>/dev/null || true)"
    [ "$img" = "$IMG" ] && { printf ' ✓\n'; break; }
    printf '.'; sleep 5
  done
done

# ── Verify on the public FQDN ─────────────────────────────────────────────────
# Green being healthy proves green is healthy; only the public FQDN proves traffic moved.
say "verifying on the public url"
for _ in $(seq 1 40); do
  AFTER="$(curl -s --max-time 20 "https://$FQDN/healthz" || echo '{}')"
  case "$AFTER" in *'"version_stamped":true'*) break ;; esac
  sleep 5
done
echo "  after: $AFTER"

case "$AFTER" in
  *'"version_stamped":true'*) ;;
  *) die "public healthz did not report a stamped version after promotion. Check traffic routing." ;;
esac

printf '\n'
ok "green ($GREEN) is live on $APP — blue ($BLUE) kept at 0%% for instant rollback"

# ── Rollback commands (printed with real names; paste, do not reconstruct) ───
cat <<ROLLBACK

  Rollback — app traffic is an instant weight change; the workers need ~20 s to pull:

    az containerapp ingress traffic set -g $RG -n $APP --revision-weight $BLUE=100 $GREEN=0
    az containerapp update -g $RG -n $DISCOVERY_WORKER --image $BLUE_IMG
    az containerapp update -g $RG -n $ASSESS_WORKER --image $BLUE_IMG
    az containerapp update -g $RG -n $REMEDIATE_WORKER --image $BLUE_IMG

  Run ALL FOUR. New workers under an old app leave the system in a mixed-version state.
  The app will stay in Multiple-revision mode (blue at 0%, green at 100%) until you
  either roll back or manually switch it to Single mode.
ROLLBACK
