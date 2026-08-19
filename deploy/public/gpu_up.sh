#!/usr/bin/env bash
# Provision the in-tenant vision GPU: Ollama on an Azure Container Apps GPU workload profile,
# in the SAME environment as acp-app, reachable only on internal ingress. Run once by hand.
#
#   bash deploy/public/gpu_up.sh                       # provision, verify, print the switch-over
#   ACP_GPU_ACTIVATE=1 bash deploy/public/gpu_up.sh    # …and flip the app onto it
#   ACP_GPU_DRY_RUN=1 bash deploy/public/gpu_up.sh     # print, change nothing
#
# WHY THIS SHAPE. Three properties are wanted at once and no other arrangement has all three:
#
#   in-tenant     internal ingress means the image bytes never leave the Container Apps
#                 environment. A VM with a public hostname does not give you this, and a
#                 third-party serverless GPU gives you the opposite.
#   scale-to-zero a GPU VM bills whether or not anyone is remediating. `--min-replicas 0` on a
#                 serverless GPU profile is the only way to keep the in-tenant property without
#                 paying for idle silicon.
#   no code       this is the EXISTING `ollama` lane. providers.local_vision_provider() builds
#                 from ai.OLLAMA_BASE_URL, which ai._maybe_refresh_endpoint() re-reads from the
#                 `ai_base_url` setting on a 30s TTL. Pointing that at this app is the whole
#                 integration — no adapter, no deploy, effective on every replica within seconds.
#
# A NOTE ON THE GOVERNANCE ZONE, because it is easy to get backwards. ACA internal FQDNs are
# `<app>.internal.<env>.<region>.azurecontainerapps.io`, and providers.zone_for_url() matches
# `.internal.` → "local". So a reviewer's provenance chip will correctly say the document never
# left your network. Give this app EXTERNAL ingress and that same chip flips to "cloud" — truthfully,
# because it would then be reachable from the internet. Internal ingress is a governance decision
# here, not a networking preference.
#
# ── THE ONE THING THIS SCRIPT WILL NOT DO WITHOUT PROOF ───────────────────────────────────────
# Azure-only means ACP_VISION_PROVIDER=ollama, and read ai.py:616 before choosing that:
#
#     if not res.get("ok") and getattr(prov, "name", "") != "ollama":
#
# The fallback floor is skipped WHEN THE PROVIDER IS ALREADY THE FLOOR. With runpod_serverless
# primary a miss degrades to Ollama; with ollama primary a miss degrades to nothing — the finding
# defers and no alt text is written. That is a defensible choice (a deferred finding is honest,
# a wrong one is not), but it means flipping the switch onto an endpoint that cannot actually
# serve the model turns every 1.1.1 remediation into a silent no-op.
#
# So the switch-over is GATED on a real generation, not on the app reporting Running. `az containerapp
# show` says nothing about whether the model is pulled, and a pull is the slow part.
set -euo pipefail

ACP="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ACP"

RG="${ACP_RG:-mdk-accessibility}"
APP="${ACP_APP:-acp-app}"
WORKER="${ACP_WORKER:-acp-worker}"
GPU_APP="${ACP_GPU_APP:-acp-ollama}"
PROFILE="${ACP_GPU_PROFILE:-NC8as-T4}"      # T4/16GB fits a quantised 7B VL model comfortably
IMAGE="${ACP_GPU_IMAGE:-docker.io/ollama/ollama:latest}"
MODEL="${ACP_GPU_VISION_MODEL:-qwen2.5vl:7b}"
DRY="${ACP_GPU_DRY_RUN:-0}"
ACTIVATE="${ACP_GPU_ACTIVATE:-0}"

say()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v az >/dev/null 2>&1 || die "az CLI not found — run this from a host logged in to Azure"

# Resolved per-call, never `az account set` — that writes a global choice another concurrent
# process can change mid-run. Same reasoning as redeploy.sh and set_integration_env.sh.
SUB="$(az account show ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} --query id -o tsv 2>/dev/null || true)"
[ -n "$SUB" ] || die "no active Azure subscription — run 'az login', or set ACP_SUBSCRIPTION"
AZ=(--subscription "$SUB")

# ── 1. the environment must be the app's own ─────────────────────────────────────────────────
# Internal ingress is only reachable from INSIDE the environment. Provisioning this in a second
# environment would produce an endpoint acp-app cannot resolve — and the failure would surface
# as vision quietly missing, not as a networking error.
ENVNAME="${ACP_ACA_ENV:-$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
  --query 'properties.environmentId' -o tsv 2>/dev/null | sed 's#.*/##')}"
[ -n "$ENVNAME" ] || die "cannot resolve the Container Apps environment from '$APP' in '$RG'.
  Set ACP_ACA_ENV explicitly, but be certain it is the environment '$APP' runs in — internal
  ingress across environments does not resolve, and the symptom is silent vision misses."
say "environment $ENVNAME  (rg=$RG, from $APP)"
[ "$DRY" = 1 ] && warn "DRY RUN — nothing will be changed"

# ── 2. the GPU workload profile ──────────────────────────────────────────────────────────────
# Serverless GPU profiles are region-limited and not enabled on every subscription. Check BEFORE
# creating the app: a create against a missing profile fails halfway and leaves a broken app.
say "checking for GPU workload profile '$PROFILE'"
HAVE="$(az containerapp env workload-profile list "${AZ[@]}" -g "$RG" -n "$ENVNAME" \
  --query "[?name=='$PROFILE'].name | [0]" -o tsv 2>/dev/null || true)"
if [ -z "$HAVE" ] || [ "$HAVE" = "None" ]; then
  if [ "$DRY" = 1 ]; then
    echo "  would: add workload profile $PROFILE"
  else
    say "adding workload profile $PROFILE"
    az containerapp env workload-profile add "${AZ[@]}" -g "$RG" -n "$ENVNAME" \
      --workload-profile-name "$PROFILE" --workload-profile-type "$PROFILE" \
      --min-nodes 0 --max-nodes 1 -o none \
      || die "could not add workload profile '$PROFILE' to '$ENVNAME'.
  Serverless GPU profiles are region- and quota-limited. Check availability in this region and
  that the subscription has GPU quota, then re-run. Nothing was created."
  fi
else
  echo "  ✓ $PROFILE already on the environment"
fi

# ── 3. the Ollama app ────────────────────────────────────────────────────────────────────────
# --min-replicas 0 is the scale-to-zero this exists for. The cost is a cold start on the first
# call after idle, which is why the app config below gives Ollama room to load the model rather
# than letting the platform kill it mid-pull.
say "provisioning $GPU_APP"
if [ "$DRY" = 1 ]; then
  echo "  would: create/update $GPU_APP on $PROFILE, internal ingress :11434, min-replicas 0"
elif az containerapp show "${AZ[@]}" -g "$RG" -n "$GPU_APP" -o none 2>/dev/null; then
  az containerapp update "${AZ[@]}" -g "$RG" -n "$GPU_APP" \
    --image "$IMAGE" --workload-profile-name "$PROFILE" \
    --min-replicas 0 --max-replicas 1 -o none \
    || die "could not update $GPU_APP"
  echo "  ✓ updated"
else
  az containerapp create "${AZ[@]}" -g "$RG" -n "$GPU_APP" --environment "$ENVNAME" \
    --image "$IMAGE" --workload-profile-name "$PROFILE" \
    --ingress internal --target-port 11434 --transport http \
    --min-replicas 0 --max-replicas 1 \
    --env-vars OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=30m -o none \
    || die "could not create $GPU_APP"
  echo "  ✓ created"
fi

FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$GPU_APP" \
  --query 'properties.configuration.ingress.fqdn' -o tsv 2>/dev/null || true)"
if [ "$DRY" != 1 ]; then
  [ -n "$FQDN" ] || die "$GPU_APP has no ingress FQDN — internal ingress did not come up"
  case "$FQDN" in
    *.internal.*) : ;;
    *) die "ingress FQDN '$FQDN' is not internal. providers.zone_for_url() would label this
  'cloud' and a reviewer's provenance chip would say the document left your network — which
  would be TRUE, because external ingress is reachable from the internet. Refusing." ;;
  esac
fi
BASE="http://${FQDN:-<pending>}:11434"
say "endpoint $BASE"

# ── 4. pull the model, from inside the environment ───────────────────────────────────────────
# `az containerapp exec` runs in the container, which is the only place this endpoint resolves.
# The pull is minutes on a cold app; it is also the step whose omission makes everything downstream
# look configured and do nothing.
if [ "$DRY" = 1 ]; then
  echo "  would: ollama pull $MODEL"
else
  say "pulling $MODEL (minutes on first run)"
  az containerapp exec "${AZ[@]}" -g "$RG" -n "$GPU_APP" \
    --command "ollama pull $MODEL" \
    || die "could not pull '$MODEL' into $GPU_APP. Nothing has been switched over — '$APP' is
  still on its current provider, which is the correct state to fail into."
fi

# ── 5. PROVE it generates, before anything is switched ───────────────────────────────────────
# The gate. `Running` proves the container started; it says nothing about whether the model is
# pulled, loaded, or able to answer. With ollama as the primary provider there is no fallback
# below it (ai.py:616), so an endpoint that cannot generate turns every 1.1.1 remediation into a
# silent defer. This asks it to generate, from a replica of the app that will be calling it.
if [ "$DRY" != 1 ]; then
  say "verifying the model actually answers"
  OUT="$(az containerapp exec "${AZ[@]}" -g "$RG" -n "$APP" --command \
    "python -c \"import json,urllib.request;r=urllib.request.urlopen(urllib.request.Request('$BASE/api/generate',data=json.dumps({'model':'$MODEL','prompt':'say ok','stream':False}).encode(),headers={'Content-Type':'application/json'}),timeout=180);print(json.load(r).get('response','')[:40])\"" \
    2>&1 || true)"
  case "$OUT" in
    *ok*|*OK*|*Ok*) echo "  ✓ generated from $APP — the lane is real, not just reachable" ;;
    *) die "the endpoint did not generate from '$APP'. NOT switching over.
  Output: $(printf '%s' "$OUT" | tr '\n' ' ' | cut -c1-300)
  Common causes: the model name '$MODEL' is not what 'ollama list' shows; the pull did not
  finish; or the GPU replica scaled to zero and the cold start exceeded the timeout. Fix and
  re-run — '$APP' is untouched, so nothing is currently broken." ;;
  esac
fi

# ── 6. switch over ───────────────────────────────────────────────────────────────────────────
# Deliberately opt-in. Provisioning and cutting production over are different decisions, and the
# gate above is only meaningful if the operator can act on it.
if [ "$ACTIVATE" != 1 ] || [ "$DRY" = 1 ]; then
  cat <<NOTE

▸ provisioned and verified — NOT yet switched over

  Re-run with ACP_GPU_ACTIVATE=1 to flip, or do it by hand:

    for A in $APP $WORKER; do
      az containerapp update -g $RG -n "\$A" --set-env-vars \\
        ACP_VISION_PROVIDER=ollama OLLAMA_BASE_URL=$BASE -o none
    done

  Both apps, because remediation runs in the WORKER (ADR 0013 §2) — the app alone would leave
  every real fix on the old provider.

  AZURE-ONLY MEANS NO SAFETY NET. With ollama as the provider, ai.py:616 skips the fallback, so
  a bad endpoint defers findings instead of degrading to a second lane. That is the honest
  failure mode, and it is why step 5 refuses to flip on an endpoint that cannot generate.

  RunPod goes inert the moment the switch flips — its vars are simply not read. Delete the
  endpoint when you are satisfied, so you stop paying for it.
NOTE
else
  say "switching $APP + $WORKER onto $BASE"
  for A in "$APP" "$WORKER"; do
    az containerapp show "${AZ[@]}" -g "$RG" -n "$A" -o none 2>/dev/null || { warn "no '$A' — skipping"; continue; }
    az containerapp update "${AZ[@]}" -g "$RG" -n "$A" --set-env-vars \
      "ACP_VISION_PROVIDER=ollama" "OLLAMA_BASE_URL=$BASE" -o none \
      || die "could not switch $A — '$APP' and '$WORKER' may now disagree; re-run before remediating"
    echo "  ✓ $A"
  done
  cat <<NOTE

▸ switched. Confirm what a scan will ACTUALLY use — the env is not the last word:

    az containerapp exec -g $RG -n $APP --command "python /app/scripts/preflight.py --live"

  Read 'resolved provider', not 'ACP_VISION_PROVIDER'. A stored admin setting
  ('ai_base_url' / 'ai_vision_provider', Settings → AI Providers) overrides the environment
  (ai.py:349, providers.py:682) and is invisible from outside the database.

  Then remediate one document with an undescribed image and read GET /scans/{sid}/ai_calls.
  That ledger records the provider and zone that actually SERVED each call, which is the only
  thing that distinguishes "we configured a GPU" from "the GPU did the work".

  RunPod is now inert. Re-run with ACP_GPU_RETIRE_RUNPOD=1 to remove its config from both apps.
NOTE
fi

# ── 7. retire RunPod ─────────────────────────────────────────────────────────────────────────
# Separate and opt-in, because it must run AFTER the switch is proven, never with it.
#
# WHY THIS IS NOT JUST TIDYING. The RunPod endpoint was stood up on a PERSONAL account as a
# stopgap while Azure GPU quota was approved. That leaves a personal credential in a production
# app's secret store: the spend lands on an individual's card, and the deployment's vision lane
# depends on an account nobody else administers. Retiring it is the point of the migration, not
# an afterthought to it.
#
# THE ORDER IS LOAD-BEARING. `RUNPOD_API_KEY=secretref:runpod-api-key` is an env var POINTING at
# a secret. Delete the secret while the reference still exists and the next revision cannot
# start — ContainerAppSecretRefNotFound, surfacing as a crash-looping app rather than as anything
# about configuration. Reference first, secret second.
if [ "${ACP_GPU_RETIRE_RUNPOD:-0}" = 1 ] && [ "$DRY" != 1 ]; then
  [ "$ACTIVATE" = 1 ] || die "ACP_GPU_RETIRE_RUNPOD=1 without ACP_GPU_ACTIVATE=1 would strip the
  RunPod lane while it is still the one serving vision. Switch over first, verify, then retire."
  say "retiring RunPod config"
  for A in "$APP" "$WORKER"; do
    az containerapp show "${AZ[@]}" -g "$RG" -n "$A" -o none 2>/dev/null || { warn "no '$A' — skipping"; continue; }
    az containerapp update "${AZ[@]}" -g "$RG" -n "$A" \
      --remove-env-vars RUNPOD_API_KEY RUNPOD_ENDPOINT_ID RUNPOD_VISION_MODEL -o none \
      || die "could not remove the RunPod env vars from $A. NOT removing the secret — doing that
  now would leave a dangling secretref and a container that cannot start. Nothing is broken:
  the vars are inert while ACP_VISION_PROVIDER=ollama."
    az containerapp secret remove "${AZ[@]}" -g "$RG" -n "$A" --secret-names runpod-api-key -o none \
      || warn "removed the env vars from $A but not the 'runpod-api-key' secret — harmless now
    that nothing references it, but delete it by hand so a personal credential is not left behind."
    echo "  ✓ $A"
  done
  cat <<NOTE

  Both apps no longer carry the personal RunPod credential. Two things this script cannot do,
  and both matter for a personal account:
    · delete the RunPod endpoint itself (runpod.io) so it stops billing
    · revoke the API key, since it has been in a container's secret store and should be treated
      as exposed regardless of who could read it
NOTE
fi
