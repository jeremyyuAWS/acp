#!/usr/bin/env bash
# Bring the whole ACP production stack up, in dependency order, and verify it.
#
# Why this exists: `az containerapp start` DOES NOT EXIST in azure-cli 2.86.0 --
# it fails as a usage error. The working route is the ARM start action via `az rest`.
# The start call prints nothing on success, so this script never trusts it: it
# re-reads properties.runningStatus from ARM until each app is Running.
#
# Safe to run when the apps are already up -- the start action is idempotent.
#
# Usage: ./acp-start-all.sh
set -uo pipefail

SUB=8fab0f8f-b577-45d7-a485-ec32f73b22be
RG=mdk-accessibility
API=2024-03-01

# Dependency order: acp-app's REDIS_URL and OLLAMA_BASE_URL point at the first two.
APPS=(acp-redis acp-ollama acp-langfuse acp-grafana acp-app acp-worker)

arm() {  # arm <app> <suffix>
  echo "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$1$2?api-version=$API"
}

status() { az rest --method get --url "$(arm "$1" '')" --query "properties.runningStatus" -o tsv 2>/dev/null; }

replicas() {
  az rest --method get --url "$(arm "$1" '/revisions')" \
    --query "length(value[?properties.active])" -o tsv 2>/dev/null
}

echo "== Starting ACP stack in dependency order =="
for app in "${APPS[@]}"; do
  cur=$(status "$app")
  if [[ "$cur" == "Running" ]]; then
    echo "  $app: already Running, skipping start"
    continue
  fi
  echo "  $app: $cur -> issuing start"
  az rest --method post --url "$(arm "$app" '/start')" >/dev/null 2>&1

  # Verify by re-reading ARM, not by trusting the (empty) command output.
  for _ in $(seq 1 30); do
    [[ "$(status "$app")" == "Running" ]] && break
    sleep 5
  done
  echo "    -> $(status "$app")"
done

echo
echo "== Verification (ARM is the source of truth; Resource Graph lags minutes) =="
fail=0
for app in "${APPS[@]}"; do
  st=$(status "$app"); rc=$(replicas "$app")
  printf '  %-14s runningStatus=%-10s activeRevisions=%s\n' "$app" "$st" "${rc:-?}"
  [[ "$st" == "Running" ]] || fail=1
done

echo
echo "== App health =="
FQDN=$(az containerapp show -g "$RG" -n acp-app --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
for ep in healthz readyz; do
  printf '  /%s: ' "$ep"
  curl -fsS --max-time 25 "https://$FQDN/$ep" 2>/dev/null || echo "unreachable"
  echo
done

if [[ $fail -ne 0 ]]; then
  echo
  echo "!! At least one app is not Running. Check the caller of the last stop:"
  echo "   az monitor activity-log list -g $RG --offset 6h \\"
  echo "     --query \"[?contains(operationName.value,'stop')].[eventTimestamp,caller]\" -o tsv"
  exit 1
fi
echo
echo "All six ACP apps Running."
