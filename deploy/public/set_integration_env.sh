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
#   1. THE APP AND THE WORKER MUST MOVE TOGETHER. Scanning happens in acp-worker (ADR 0013 §2:
#      the API runs ACP_WORKERS=0 and serves only). Langfuse configured on acp-app alone gives
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
#     bash deploy/public/set_integration_env.sh            # fully non-interactive
#   ACP_SET_ENV_DRY_RUN=1 bash deploy/public/set_integration_env.sh   # print, change nothing
#
# Each group is INDEPENDENT: supply only the Langfuse inputs and SharePoint is left alone, and
# vice versa. A group with no inputs is skipped and said to be skipped — never silently.
set -euo pipefail

RG="${ACP_RG:-mdk-accessibility}"
APP="${ACP_APP:-acp-app}"
WORKER="${ACP_WORKER:-acp-worker}"
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
if az containerapp show "${AZ[@]}" -g "$RG" -n "$WORKER" -o none 2>/dev/null; then
  TARGETS+=("$WORKER")
else
  # Not fatal: a single-tier deployment (ACP_DEPLOY_WORKER unset) genuinely has no worker. Said
  # out loud, because "the worker was skipped" and "there is no worker" must not look alike.
  warn "no container app '$WORKER' in '$RG' — single-tier deployment, configuring '$APP' only"
fi
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
      || die "could not set Langfuse secrets on $A — stopping so '$APP' and '$WORKER' do not end up on different configs"
    # --set-env-vars is ADDITIVE: it updates only the names listed and leaves DATABASE_URL, the
    # RunPod vars and everything else untouched. That is what makes this safe against a live app,
    # and it is the same semantic deploy.sh relies on.
    _retry az containerapp update "${AZ[@]}" -g "$RG" -n "$A" --set-env-vars \
      "LANGFUSE_HOST=$LF_HOST" "LANGFUSE_PUBLIC_KEY=secretref:langfuse-pk" \
      "LANGFUSE_SECRET_KEY=secretref:langfuse-sk" -o none \
      || die "could not set Langfuse env on $A — '$APP' and '$WORKER' may now disagree; re-run before deploying"
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

# ── read back ──────────────────────────────────────────────────────────────────────────────
# NAMES and secretREFS only, never values. The point is to prove the wiring landed on BOTH apps:
# a secretref pointing at a secret that does not exist is a ContainerAppSecretRefNotFound at
# container start, which surfaces as a crash-looping revision rather than as anything about
# configuration.
if [ "$DRY" != 1 ]; then
  say "verifying"
  for A in "${TARGETS[@]}"; do
    printf '  %s\n' "$A"
    for V in LANGFUSE_HOST LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY ACP_AZURE_CLIENT_ID ACP_AZURE_TENANT_ID; do
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
