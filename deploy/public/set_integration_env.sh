#!/usr/bin/env bash
# Set the Langfuse and SharePoint/Entra configuration on a LIVE acp deployment.
#
#   deploy.sh                = FIRST deploy. Re-derives all environment from scratch.
#   redeploy.sh              = image only. Every env var and secret survives untouched.
#   set_integration_env.sh   = THIS. Environment only. Never touches the image.
#
# The gap this fills: redeploy.sh deliberately leaves configuration alone, so there was no
# supported way to add an integration to a running app short of deploy.sh — which blanks
# DATABASE_URL back to SQLite and mints a new access code. Operators were left hand-rolling
# `az containerapp update` calls, which is where the two failures below come from.
#
# WHY A SCRIPT RATHER THAN TWO az COMMANDS IN A RUNBOOK.
#
#   1. THE APP AND ALL STAGE WORKERS MUST MOVE TOGETHER. The API runs ACP_WORKERS=0 and serves
#      only. Langfuse configured on acp-app alone gives
#      you traces for the API and NOTHING for Discover — which looks like "tracing is broken"
#      rather than "tracing is half-configured". redeploy.sh's header already warns that the two
#      running different configs is a real failure mode; this enforces it instead of describing
#      it. If the worker exists and cannot be updated, this script FAILS rather than leaving the
#      pair split.
#   2. A SECRET ON A COMMAND LINE IS IN THE SHELL HISTORY AND IN `ps`. LANGFUSE_SECRET_KEY is
#      read from the environment or prompted for with `read -rs`; it is never an argv element of
#      anything this script echoes, and az failures are scrubbed before they are printed.
#
# Usage:
#   bash deploy/public/set_integration_env.sh              # prompts for whatever is missing
#   LANGFUSE_SECRET_KEY=sk-lf-… ACP_AZURE_CLIENT_ID=… ACP_AZURE_TENANT_ID=… \
#     RUNPOD_ENDPOINT_ID=… RUNPOD_API_KEY=… \
#     bash deploy/public/set_integration_env.sh            # fully non-interactive
#   RUNPOD_ENDPOINT_ID=… RUNPOD_API_KEY=… \
#     bash deploy/public/set_integration_env.sh            # just the GPU switch
#   ACP_SET_ENV_DRY_RUN=1 bash deploy/public/set_integration_env.sh   # print, change nothing
#
# Three groups — Langfuse, SharePoint/Entra, GPU vision — and each is INDEPENDENT: supply only
# the Langfuse inputs and the other two are left alone. A group with no inputs is skipped and
# said to be skipped — never silently.
#
# THIS IS NOT redeploy.sh's JOB AND DOES NOT NEED IT. Every variable here is read at runtime
# (providers.py, core.py, lf.py all read os.environ), so `az containerapp update --set-env-vars`
# provisions a new revision and the change is live. redeploy.sh swaps the IMAGE and leaves env
# untouched by design — running it to "apply" a config change rebuilds for three minutes and
# changes nothing.
set -euo pipefail

RG="${ACP_RG:-mdk-accessibility}"
APP="${ACP_APP:-acp-app}"
DISCOVERY_WORKER="${ACP_DISCOVERY_WORKER:-acp-discovery}"
ASSESS_WORKER="${ACP_ASSESS_WORKER:-acp-assess}"
REMEDIATE_WORKER="${ACP_REMEDIATE_WORKER:-acp-remediate}"
STAGE_WORKERS=("$DISCOVERY_WORKER" "$ASSESS_WORKER" "$REMEDIATE_WORKER")
DRY="${ACP_SET_ENV_DRY_RUN:-0}"

# Same defaults deploy.sh carries, so this script and that one cannot disagree about which
# Langfuse project the demo points at. The public key is NOT a secret, but it MUST pair with the
# secret key: both belong to one project (acp-compliance — matches LANGFUSE_INIT_PROJECT_* on
# acp-langfuse). A pk from one project with an sk from another authenticates and then writes
# traces nobody is looking at, which is the silent-and-reassuring failure again.
LF_HOST="${LANGFUSE_HOST:-https://acp-langfuse.greenwater-4bf2c997.eastus2.azurecontainerapps.io}"
LF_PK="${LANGFUSE_PUBLIC_KEY:-pk-lf-655083d12dacf12febf1f1e8d2293905}"
LF_SK="${LANGFUSE_SECRET_KEY:-}"

CID="${ACP_AZURE_CLIENT_ID:-}"
TID="${ACP_AZURE_TENANT_ID:-}"

# GPU vision (ADR 0022). RUNPOD_ENDPOINT_ID is non-secret config; RUNPOD_API_KEY is the ops
# secret. ACP_VISION_PROVIDER is the switch that decides whether the other two are used AT ALL —
# set the pair and leave this on 'ollama' and vision keeps working, on the local CPU floor, with
# nothing anywhere saying so. Observed in production on 2026-08-19: the endpoint was warm at
# `workers ready=2` while every scan went to the CPU.
RP_EID="${RUNPOD_ENDPOINT_ID:-}"
RP_KEY="${RUNPOD_API_KEY:-}"
RP_MODEL="${RUNPOD_VISION_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"

say()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v az >/dev/null 2>&1 || die "az CLI not found — this must run from a host logged in to Azure"

# Resolved per-call, never via `az account set`: that writes a global choice another concurrent
# process can change mid-run. Same reasoning as redeploy.sh.
SUB="$(az account show ${ACP_SUBSCRIPTION:+--subscription "$ACP_SUBSCRIPTION"} --query id -o tsv 2>/dev/null || true)"
[ -n "$SUB" ] || die "no active Azure subscription — run 'az login', or set ACP_SUBSCRIPTION"
AZ=(--subscription "$SUB")

# ACA serializes revision writes; this is the conflict it raises when two overlap. Lifted from
# deploy.sh — updating two apps back to back hits it routinely.
_retry() {
  local i
  for i in 1 2 3 4 5 6; do
    if "$@" 2>/tmp/acp_setenv_err; then return 0; fi
    grep -qi "conflicting concurrent write" /tmp/acp_setenv_err || { cat /tmp/acp_setenv_err >&2; return 1; }
    echo "   ...ACA busy, retry $i"; sleep 12
  done
  cat /tmp/acp_setenv_err >&2; return 1
}

# az echoes the failing request on error, and for `secret set` that request CONTAINS the secret.
# Print a shape, not a body.
_scrubbed() {
  if "$@" >/dev/null 2>/tmp/acp_setenv_err; then return 0; fi
  echo "   az call failed: $(grep -oE '\([A-Za-z]+\)' /tmp/acp_setenv_err | head -1 || echo '(unknown)')" \
       "— full output suppressed (may contain secret material); see /tmp/acp_setenv_err locally" >&2
  return 1
}

# ── which apps ─────────────────────────────────────────────────────────────────────────────
TARGETS=()
az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" -o none 2>/dev/null \
  || die "no container app '$APP' in resource group '$RG' — check ACP_RG/ACP_APP"
TARGETS+=("$APP")
for A in "${STAGE_WORKERS[@]}"; do
  az containerapp show "${AZ[@]}" -g "$RG" -n "$A" -o none 2>/dev/null \
    || die "no stage worker '$A' in '$RG' — refusing to split integration configuration"
  TARGETS+=("$A")
done
say "targets: ${TARGETS[*]}  (rg=$RG)"
[ "$DRY" = 1 ] && warn "DRY RUN — nothing will be changed"

# ── Langfuse ───────────────────────────────────────────────────────────────────────────────
if [ -z "$LF_SK" ] && [ -t 0 ] && [ "$DRY" != 1 ]; then
  read -rs -p "LANGFUSE_SECRET_KEY (blank to skip Langfuse): " LF_SK; echo
fi

if [ -z "$LF_SK" ]; then
  warn "Langfuse SKIPPED — no LANGFUSE_SECRET_KEY. Tracing stays off: every lf.* call is a
    no-op by design, so runs complete and trace nothing."
else
  case "$LF_SK" in sk-lf-*) ;; *) die "LANGFUSE_SECRET_KEY does not start with 'sk-lf-' — refusing to set a key that is almost certainly the wrong value" ;; esac
  case "$LF_PK" in pk-lf-*) ;; *) die "LANGFUSE_PUBLIC_KEY does not start with 'pk-lf-'" ;; esac
  say "Langfuse → host=$LF_HOST  pk=${LF_PK:0:11}…  sk=(present, not shown)"
  for A in "${TARGETS[@]}"; do
    echo "  $A"
    if [ "$DRY" = 1 ]; then
      echo "    would: secret set langfuse-pk/langfuse-sk; set-env-vars LANGFUSE_{HOST,PUBLIC_KEY,SECRET_KEY}"
      continue
    fi
    _scrubbed az containerapp secret set "${AZ[@]}" -g "$RG" -n "$A" \
      --secrets "langfuse-pk=$LF_PK" "langfuse-sk=$LF_SK" -o none \
      || die "could not set Langfuse secrets on $A — stopping before the stage workers drift"
    # --set-env-vars is ADDITIVE: it updates only the names listed and leaves DATABASE_URL, the
    # RunPod vars and everything else untouched. That is what makes this safe against a live app,
    # and it is the same semantic deploy.sh relies on.
    _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$A" --set-env-vars \
      "LANGFUSE_HOST=$LF_HOST" "LANGFUSE_PUBLIC_KEY=secretref:langfuse-pk" \
      "LANGFUSE_SECRET_KEY=secretref:langfuse-sk" -o none \
      || die "could not set Langfuse env on $A — the stage workers may now disagree; re-run before deploying"
  done
fi

# ── SharePoint / OneDrive (Microsoft Graph) ────────────────────────────────────────────────
# Neither of these is a secret. A public-client application id and a tenant id are printed in
# every sign-in URL the SPA generates; storing them as ACA secrets would buy nothing and would
# make them harder to read back when diagnosing a failed connect.
if [ -z "$CID" ] && [ -t 0 ] && [ "$DRY" != 1 ]; then
  read -r -p "ACP_AZURE_CLIENT_ID  (Entra app id, blank to skip SharePoint): " CID
  [ -n "$CID" ] && read -r -p "ACP_AZURE_TENANT_ID (blank => multi-tenant 'common'): " TID
fi

if [ -z "$CID" ]; then
  warn "SharePoint SKIPPED — no ACP_AZURE_CLIENT_ID. /config returns null and the SPA HIDES the
    Connect Microsoft button, which reads as 'SharePoint is not part of this build'."
else
  [ -n "$TID" ] || warn "ACP_AZURE_TENANT_ID not set — sign-in falls back to the multi-tenant 'common' authority"
  say "SharePoint → client_id=$CID  tenant=${TID:-common}"
  for A in "${TARGETS[@]}"; do
    echo "  $A"
    if [ "$DRY" = 1 ]; then
      echo "    would: set-env-vars ACP_AZURE_CLIENT_ID${TID:+, ACP_AZURE_TENANT_ID}"
      continue
    fi
    _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$A" --set-env-vars \
      "ACP_AZURE_CLIENT_ID=$CID" ${TID:+"ACP_AZURE_TENANT_ID=$TID"} -o none \
      || die "could not set Entra config on $A"
  done
fi

# ── GPU vision (RunPod Serverless, ADR 0022) ───────────────────────────────────────────────
# The endpoint id is non-secret config (serverless_up.sh says so in as many words); only the key
# is an ops secret, so it goes in as a secretref and the id does not.
#
# THE SWITCH IS THE POINT. `providers.active_vision_provider()` reads ACP_VISION_PROVIDER and
# defaults to 'ollama' — so the endpoint id and key can both be present and correct while every
# scan runs on the local CPU floor. Nothing errors; the only symptom is that vision is slow,
# which reads as "the GPU is not very fast". All three move together here for that reason: a
# group that set the credentials and left the switch alone would reproduce the exact failure.
if [ -z "$RP_EID" ] && [ -t 0 ] && [ "$DRY" != 1 ]; then
  read -r -p "RUNPOD_ENDPOINT_ID (blank to skip GPU vision): " RP_EID
  [ -n "$RP_EID" ] && { read -rs -p "RUNPOD_API_KEY: " RP_KEY; echo; }
fi

if [ -z "$RP_EID" ]; then
  warn "GPU vision SKIPPED — no RUNPOD_ENDPOINT_ID. Vision stays on the local CPU floor."
else
  [ -n "$RP_KEY" ] || die "RUNPOD_ENDPOINT_ID without RUNPOD_API_KEY — the id alone is not enough
    (serverless_vision_provider() returns None), and setting ACP_VISION_PROVIDER=runpod_serverless
    with a half-configured endpoint silently falls back to the CPU floor. Refusing to do that."
  say "GPU vision → endpoint=$RP_EID  model=$RP_MODEL  key=(present, not shown)"
  for A in "${TARGETS[@]}"; do
    echo "  $A"
    if [ "$DRY" = 1 ]; then
      echo "    would: secret set runpod-api-key; set-env-vars ACP_VISION_PROVIDER, RUNPOD_ENDPOINT_ID, RUNPOD_VISION_MODEL"
      continue
    fi
    _scrubbed az containerapp secret set "${AZ[@]}" -g "$RG" -n "$A" \
      --secrets "runpod-api-key=$RP_KEY" -o none \
      || die "could not set the RunPod key on $A — stopping before the stage workers drift"
    _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$A" --set-env-vars \
      "ACP_VISION_PROVIDER=runpod_serverless" "RUNPOD_ENDPOINT_ID=$RP_EID" \
      "RUNPOD_API_KEY=secretref:runpod-api-key" "RUNPOD_VISION_MODEL=$RP_MODEL" -o none \
      || die "could not set GPU vision env on $A — the stage workers may now disagree; re-run before scanning"
  done
  # An ADMIN SETTING OVERRIDES THE ENV, and this script cannot see or change it: providers.py
  # reads store.get_setting('ai_vision_provider') after the env and lets it win. So the env being
  # right is necessary and not sufficient, and the only honest check is the resolver itself.
  warn "env is set — now confirm what a scan will ACTUALLY use. providers.active_vision_provider()
    lets a stored admin setting ('ai_vision_provider', from Settings → AI Providers) override the
    env, and that override is invisible from the environment alone. Run the preflight IN the
    container and read the 'resolved provider' line, not the 'ACP_VISION_PROVIDER' one:
      az containerapp exec -g $RG -n $APP --command \"python /app/scripts/preflight.py --live\"
    If ACP_VISION_PROVIDER now passes but 'resolved provider' still says ollama, the admin
    setting is pinned — change it in Settings → AI Providers."
fi

# ── read back ──────────────────────────────────────────────────────────────────────────────
# NAMES and secretREFS only, never values. The point is to prove the wiring landed on BOTH apps:
# a secretref pointing at a secret that does not exist is a ContainerAppSecretRefNotFound at
# container start, which surfaces as a crash-looping revision rather than as anything about
# configuration.
if [ "$DRY" != 1 ]; then
  say "verifying"
  for A in "${TARGETS[@]}"; do
    printf '  %s\n' "$A"
    for V in LANGFUSE_HOST LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY ACP_AZURE_CLIENT_ID ACP_AZURE_TENANT_ID \
             ACP_VISION_PROVIDER RUNPOD_ENDPOINT_ID RUNPOD_API_KEY RUNPOD_VISION_MODEL; do
      REF="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$A" \
        --query "properties.template.containers[0].env[?name=='$V'].secretRef | [0]" -o tsv 2>/dev/null || true)"
      VAL="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$A" \
        --query "properties.template.containers[0].env[?name=='$V'].value | [0]" -o tsv 2>/dev/null || true)"
      if [ -n "$REF" ] && [ "$REF" != "None" ]; then
        printf '    ✓ %-22s secretref:%s\n' "$V" "$REF"
      elif [ -n "$VAL" ] && [ "$VAL" != "None" ]; then
        printf '    ✓ %-22s %s\n' "$V" "$VAL"
      else
        printf '    · %-22s not set\n' "$V"
      fi
    done
  done
fi

say "next"
cat <<NOTE
  A new revision is provisioning. Give it ~30s, then confirm the app came up:
    az containerapp revision list -g $RG -n $APP \\
      --query "[0].{name:name,active:properties.active,state:properties.runningState}" -o table

  scripts/preflight.py reads the environment of the SHELL IT RUNS IN, not the deployment. It will
  keep reporting SharePoint and Tracing as WARN on your laptop no matter what this script set in
  Azure — that is the preflight being honest about what it can see, not a failure. To check the
  DEPLOYED config, use the read-back above, or run the preflight inside the container:
    az containerapp exec -g $RG -n $APP --command "python /app/scripts/preflight.py --live"

  That path is absolute on purpose. The image's WORKDIR is /app/api (Dockerfile), so a relative
  "scripts/preflight.py" resolves to /app/api/scripts and is not there. Expect one WARN that is
  an artifact of the container rather than a finding: "delegated scopes — could not read
  sharepointScopes.js". Only the BUILT SPA ships in the image (/app/static), not frontend/src,
  so the preflight cannot read the scope list back from source there. Every other check is real.

  SharePoint's Graph scopes are DELEGATED — a person signs in, so nothing headless can verify
  token acquisition. Verify by clicking Connect Microsoft in the app.
NOTE
