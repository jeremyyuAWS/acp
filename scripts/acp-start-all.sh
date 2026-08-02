#!/usr/bin/env bash
# Bring the whole ACP production stack up, in dependency order, and prove that it came up.
#
# ── why this script exists at all ──────────────────────────────────────────────────────────
#
# `az containerapp start` DOES NOT EXIST in azure-cli 2.86.0. It fails as a usage error, not as
# a missing-resource error, which reads like a typo rather than a missing feature — and one
# session has already reported starting the stack on the strength of it without anything having
# started. The working route is the ARM start action via `az rest`.
#
# The start action returns an EMPTY BODY on success. There is therefore nothing in the command's
# output to check, and every verification below re-reads state from ARM instead. Do not "simplify"
# this by trusting an exit code: `az rest` exits 0 for an accepted request, and acceptance is not
# readiness.
#
# Recovering the stack by hand means six of those calls in the right order. Production has been
# found fully stopped twice, both times by accident, so the recovery path is walked under time
# pressure by someone who did not plan their morning around it. That is the worst moment to be
# assembling ARM URLs from a doc.
#
# ── order matters ──────────────────────────────────────────────────────────────────────────
#
# acp-app's REDIS_URL and OLLAMA_BASE_URL point at acp-redis and acp-ollama. Starting the app
# first gives you an app that boots, fails to reach its dependencies, and needs restarting again.
# Dependencies first, consumers last.
#
# Safe to run when the stack is already up: the start action is idempotent, and an app already
# Running is skipped rather than restarted.
#
# Usage:  ./scripts/acp-start-all.sh          # start and verify
#         ./scripts/acp-start-all.sh --check  # verify only, change nothing
#
# Exit 0 = all six Running. Exit 1 = at least one is not, or the app is not serving.
set -uo pipefail

SUB=8fab0f8f-b577-45d7-a485-ec32f73b22be
RG=mdk-accessibility
API=2024-03-01

# Dependency order. acp-app and acp-worker run the same image and must both be up: scanning
# happens in the worker, so an app-only stack serves a UI that never finishes a scan.
APPS=(acp-redis acp-ollama acp-langfuse acp-grafana acp-app acp-worker)

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

arm() {  # arm <app> [suffix]
  printf 'https://management.azure.com/subscriptions/%s/resourceGroups/%s/providers/Microsoft.App/containerApps/%s%s?api-version=%s' \
    "$SUB" "$RG" "$1" "${2:-}" "$API"
}

# NOTE: every --query below is quoted. Unquoted `properties.template.containers[0].image` is
# glob-expanded by zsh, which prints "no matches found" and never runs az at all — a polling loop
# built on that reports an empty image and looks exactly like a failed deploy.
status()   { az rest --method get --url "$(arm "$1")" --query "properties.runningStatus" -o tsv 2>/dev/null; }
replicas() { az rest --method get --url "$(arm "$1" /revisions)" \
               --query "sum(value[?properties.active].properties.replicas)" -o tsv 2>/dev/null; }
serving()  { az rest --method get --url "$(arm "$1" /revisions)" \
               --query "sum(value[?properties.trafficWeight>\`0\`].properties.replicas)" -o tsv 2>/dev/null; }
# acp-worker has NO ingress — it pulls from the queue and serves nothing. Traffic weight is
# therefore meaningless for it, and asserting on it reports a permanently broken worker on a
# perfectly healthy stack. Asked per app rather than hardcoded so the check follows the topology.
ingress()  { az rest --method get --url "$(arm "$1")" \
               --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null; }

az account show >/dev/null 2>&1 || { echo "not logged in to Azure — run 'az login'"; exit 1; }

# ── start ──────────────────────────────────────────────────────────────────────────────────
if [ "$CHECK_ONLY" = 0 ]; then
  echo "== Starting the ACP stack in dependency order =="
  for app in "${APPS[@]}"; do
    cur=$(status "$app")
    if [ "$cur" = "Running" ]; then
      echo "  $app: already Running — skipping"
      continue
    fi
    echo "  $app: ${cur:-unknown} -> issuing start"
    az rest --method post --url "$(arm "$app" /start)" >/dev/null 2>&1

    # Re-read ARM until it agrees. The start call told us nothing.
    for _ in $(seq 1 30); do
      [ "$(status "$app")" = "Running" ] && break
      sleep 5
    done
    echo "    -> $(status "$app")"
  done
  echo
fi

# ── verify ─────────────────────────────────────────────────────────────────────────────────
echo "== Verification (ARM is the source of truth; Resource Graph lags by minutes) =="
fail=0
for app in "${APPS[@]}"; do
  st=$(status "$app"); rc=$(replicas "$app")
  if [ -n "$(ingress "$app")" ]; then
    sv=$(serving "$app")
    printf '  %-14s runningStatus=%-10s replicas=%-4s serving=%s\n' "$app" "${st:-?}" "${rc:-0}" "${sv:-0}"
    # A revision can be Running with every replica on 0% traffic — the blue-green failure mode,
    # where an --image update lands a revision that never serves a request. Running is not serving.
    if [ "$st" = "Running" ] && [ "${sv:-0}" = "0" ]; then
      echo "    !! Running but NO replica is taking traffic — check revision traffic weights"
      fail=1
    fi
  else
    printf '  %-14s runningStatus=%-10s replicas=%-4s (no ingress — queue worker)\n' \
      "$app" "${st:-?}" "${rc:-0}"
  fi
  [ "$st" = "Running" ] || fail=1
done

# ── is it actually answering? ──────────────────────────────────────────────────────────────
echo
echo "== App health =="
FQDN=$(az containerapp show -g "$RG" -n acp-app --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
if [ -z "$FQDN" ]; then
  echo "  could not resolve acp-app's FQDN"
  fail=1
else
  for ep in healthz readyz; do
    body=$(curl -fsS --max-time 25 "https://$FQDN/$ep" 2>/dev/null)
    if [ -z "$body" ]; then
      printf '  /%s: unreachable\n' "$ep"; fail=1
    elif printf '%s' "$body" | grep -qi '<html'; then
      # A stopped container app answers with Azure's own HTML error page, not with nothing. A
      # deploy was once reported as failed on the strength of that page when the real story was
      # that the apps had been stopped beforehand by something else entirely.
      printf '  /%s: HTML, not JSON — this is Azure'"'"'s stopped-app page, not the application\n' "$ep"
      fail=1
    else
      printf '  /%s: %s\n' "$ep" "$(printf '%s' "$body" | head -c 200)"
    fi
  done
fi

if [ "$fail" -ne 0 ]; then
  cat <<EOF

!! The stack is not fully up. If it stopped on its own, find out who stopped it:

   az monitor activity-log list -g $RG --offset 6h \\
     --query "[?contains(operationName.value,'stop')].[eventTimestamp,caller]" -o tsv

   A recurring overnight stop is demo-manager-api hibernating the estate on a tag match --
   that is a separate, known issue with its own owner; this script only gets you back up.
EOF
  exit 1
fi

echo
echo "All six ACP apps are Running and serving."
