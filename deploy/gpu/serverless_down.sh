#!/usr/bin/env bash
# Delete the RunPod serverless endpoint (+ its template). Scale-to-zero means an idle endpoint costs
# nothing, so this is only for a full teardown. Key read from ~/.zshrc, never printed.
set -euo pipefail
KEY=$(grep -E '^[[:space:]]*export[[:space:]]+RUNPOD_API_KEY=' ~/.zshrc | head -1 | sed -E 's/.*RUNPOD_API_KEY=//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//')
UA="Mozilla/5.0"
GQL="https://api.runpod.io/graphql?api_key=$KEY"
EID="${1:-$(cat /tmp/acp_runpod_serverless_id 2>/dev/null || true)}"
[ -n "$KEY" ] && [ -n "$EID" ] || { echo "usage: serverless_down.sh <endpoint_id>"; exit 1; }
curl -s -H "content-type: application/json" -H "User-Agent: $UA" "$GQL" \
  -d "{\"query\":\"mutation { deleteEndpoint(id: \\\"$EID\\\") }\"}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('deleted' if 'errors' not in d else d['errors'])"
rm -f /tmp/acp_runpod_serverless_id
