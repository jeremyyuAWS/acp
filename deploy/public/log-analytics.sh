#!/usr/bin/env bash
# Provision the Log Analytics workspace the Live Operations system-log panel reads.
#
# WHY THIS IS SEPARATE FROM THE APP. Container Apps writes system logs — image-pull failures,
# volume mount errors, container crash output, revision provisioning failures — to a Log Analytics
# workspace or nowhere. Until one exists, the Deployments panel names the gap and shows nothing,
# which is honest but not useful. This closes it.
#
# WHAT IT COSTS, said out loud because a log workspace is a metered resource and this script is
# how it gets created. Log Analytics bills per GB ingested and per GB retained beyond the free
# tier. A chatty container can produce a surprising bill, so the workspace is created with a
# 30-day retention and a daily ingestion CAP rather than unlimited — the cap makes the failure
# mode "logs stop for the day", which is recoverable, instead of an invoice nobody expected.
#
# IT IS NOT LIVE. Log Analytics ingestion for Container Apps lags roughly two to three minutes.
# The panel labels every row as delayed for that reason; nothing here makes it faster.
#
# UNVERIFIED against a live subscription, like the rest of this repo's Azure code. Run --dry-run
# first; it prints the exact az invocations without sending them.
set -euo pipefail

SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-8fab0f8f-b577-45d7-a485-ec32f73b22be}"
RESOURCE_GROUP="${ACP_RESOURCE_GROUP:-mdk-accessibility}"
WORKSPACE="${ACP_LOG_WORKSPACE_NAME:-acp-logs}"
RETENTION_DAYS="${ACP_LOG_RETENTION_DAYS:-30}"
# Gigabytes per day. -1 means uncapped; this default is deliberately finite.
DAILY_CAP_GB="${ACP_LOG_DAILY_CAP_GB:-1}"
read -r -a APPS <<< "${WORKER_APP_NAMES_SPACED:-acp-assess acp-remediate acp-discovery}"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

run() {
  if $DRY_RUN; then
    printf 'az'; printf ' %q' "$@"; printf '\n'
  else
    az "$@" --output none
  fi
}

echo "Workspace $WORKSPACE (retention ${RETENTION_DAYS}d, daily cap ${DAILY_CAP_GB}GB):"
run monitor log-analytics workspace create \
  --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$WORKSPACE" \
  --retention-time "$RETENTION_DAYS" \
  --quota "$DAILY_CAP_GB"

if $DRY_RUN; then
  WORKSPACE_ID='<workspace customerId, read after creation>'
else
  # The CUSTOMER ID (a GUID), not the ARM resource id: LogsQueryClient.query_workspace takes the
  # former, and passing the latter fails with an unhelpful 404 that looks like a missing grant.
  WORKSPACE_ID="$(az monitor log-analytics workspace show \
    --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$WORKSPACE" --query customerId -o tsv)"
fi

# Point each container app's diagnostics at the workspace. Without this the workspace exists and
# stays empty, which reads exactly like a workspace that is not configured at all.
for app in "${APPS[@]}"; do
  echo "  wiring $app diagnostics"
  run monitor diagnostic-settings create \
    --subscription "$SUBSCRIPTION" \
    --name "${app}-system-logs" \
    --resource "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${app}" \
    --workspace "$WORKSPACE" \
    --logs '[{"category":"ContainerAppSystemLogs","enabled":true}]'
done

echo
echo "Set this on the API and worker apps to turn the panel on:"
echo "  LOG_ANALYTICS_WORKSPACE_ID=${WORKSPACE_ID}"
echo
echo "The identity ACP runs as also needs the Log Analytics Reader role on the workspace."
echo "The azure-monitor-query package is already declared in api/requirements.txt, so no"
echo "rebuild is needed beyond setting the variable above."
echo "Rows will be labelled delayed: ingestion lags roughly three minutes and this does not change that."
