#!/usr/bin/env bash
# Apply the reviewed production capacity baseline without changing images or secrets.
set -euo pipefail

SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-8fab0f8f-b577-45d7-a485-ec32f73b22be}"
RESOURCE_GROUP="${ACP_RESOURCE_GROUP:-mdk-accessibility}"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

update_app() {
  local name="$1" cpu="$2" memory="$3" min="$4" max="$5"
  local args=(containerapp update --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP"
    --name "$name" --cpu "$cpu" --memory "$memory" --min-replicas "$min" --max-replicas "$max")
  if $DRY_RUN; then
    printf 'az'
    printf ' %q' "${args[@]}"
    printf '\n'
  else
    echo "Right-sizing $name ($cpu CPU, $memory, replicas $min-$max)"
    az "${args[@]}" --output none
  fi
}

# The web tier retains burst headroom. Discovery can now use its existing CPU
# scale rule. Assess and Remediate retain four worker processes apiece across
# two replicas, while avoiding five permanently warm replicas per stage.
update_app acp-app       1.0 2Gi 1 3
update_app acp-discovery 1.0 2Gi 1 2
update_app acp-assess    2.0 4Gi 2 2
update_app acp-remediate 2.0 4Gi 2 2

# Production and staging point at acp-ollama-gpu. Keep this legacy fallback
# available but cold until explicitly addressed through its internal ingress.
update_app acp-ollama    4.0 8Gi 0 1

if ! $DRY_RUN; then
  echo "Production capacity baseline applied."
fi
