#!/usr/bin/env bash
# Apply the reviewed production capacity baseline without changing images or secrets.
set -euo pipefail

SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-8fab0f8f-b577-45d7-a485-ec32f73b22be}"
RESOURCE_GROUP="${ACP_RESOURCE_GROUP:-mdk-accessibility}"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

update_app() {
  local name="$1" cpu="$2" memory="$3" min="$4" max="$5" db_pool="${6:-}"
  local args=(containerapp update --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP"
    --name "$name" --cpu "$cpu" --memory "$memory" --min-replicas "$min" --max-replicas "$max")
  if [[ -n "$db_pool" ]]; then
    args+=(--set-env-vars "ACP_DB_MAX_CONN=$db_pool")
  fi
  if $DRY_RUN; then
    printf 'az'
    printf ' %q' "${args[@]}"
    printf '\n'
  else
    echo "Right-sizing $name ($cpu CPU, $memory, replicas $min-$max)"
    az "${args[@]}" --output none
  fi
}

apply_remediation_autoscale() {
  local args=(containerapp update --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP"
    --name acp-remediate --scale-rule-name remediation-queue
    --scale-rule-type postgresql
    --scale-rule-metadata
      "query=SELECT count(*) FROM jobs WHERE status='queued' AND type IN ('remediate_file','rescore_file','apply_approved_values')"
      "targetQueryValue=4"
    --scale-rule-auth "connection=database-url")
  if $DRY_RUN; then
    printf 'az'
    printf ' %q' "${args[@]}"
    printf '\n'
  else
    echo "Enabling Remediation queue autoscale (4 queued jobs per replica)"
    az "${args[@]}" --output none
  fi
}

# The web tier retains burst headroom. Discovery can use its existing CPU scale
# rule. Assessment and Remediation are throughput-sensitive batch stages: keep
# five replicas warm so large runs retain the production performance baseline.
update_app acp-app       1.0 2Gi 1 3
# Dedicated worker replicas serve no HTTP traffic. Their two job threads share a two-connection
# pool; scheduler/heartbeat operations wait briefly for a slot instead of reserving idle
# connections. This keeps the full fleet beneath Postgres's measured 150-connection ceiling,
# including old+new revision overlap during deploy.
update_app acp-discovery 1.0 2Gi 1 2  2
update_app acp-assess    2.0 4Gi 5 5  2
update_app acp-remediate 2.0 4Gi 5 10 2
apply_remediation_autoscale

# Production and staging point at acp-ollama-gpu. Keep this legacy fallback
# available but cold until explicitly addressed through its internal ingress.
update_app acp-ollama    4.0 8Gi 0 1

if ! $DRY_RUN; then
  echo "Production capacity baseline applied."
fi
