#!/usr/bin/env bash
# Point the ACP apps at a Langfuse host and verify. Used to cut over to v3, and (with the old
# host) to roll back. Only LANGFUSE_HOST moves — the pk/sk are unchanged because v3 was seeded
# with the same project keys.
#
#   ./cutover.sh https://acp-langfuse-v3.eastus2.cloudapp.azure.com      # cut over to v3
#   ./cutover.sh https://acp-langfuse.greenwater-….azurecontainerapps.io # roll back to v2
set -euo pipefail
RG="${RG:-mdk-accessibility}"
HOST="${1:?usage: cutover.sh <LANGFUSE_HOST-url>}"
APPS=(${APPS:-acp-app acp-discovery acp-assess acp-remediate})

for app in "${APPS[@]}"; do
  echo "▸ $app → LANGFUSE_HOST=$HOST"
  az containerapp update -g "$RG" -n "$app" --set-env-vars "LANGFUSE_HOST=$HOST" -o none
done
echo "▸ verify:"
for app in "${APPS[@]}"; do
  v=$(az containerapp show -g "$RG" -n "$app" --query "properties.template.containers[0].env[?name=='LANGFUSE_HOST'].value | [0]" -o tsv)
  r=$(az containerapp show -g "$RG" -n "$app" --query "properties.latestRevisionName" -o tsv)
  echo "  $app: $v  (rev $r)"
done
echo "Run a scan; then confirm traces land in the target Langfuse (Tracing → Traces) and the"
echo "Session view loads. To roll back, re-run this with the previous host."
