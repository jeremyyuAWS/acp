#!/usr/bin/env bash
# Terminate the burst GPU pod. Key is read from ~/.zshrc and NEVER printed.
set -euo pipefail
KEY=$(grep -E '^[[:space:]]*export[[:space:]]+RUNPOD_API_KEY=' ~/.zshrc | head -1 | sed -E 's/.*RUNPOD_API_KEY=//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//')
PID="${1:-$(cat /tmp/acp_runpod_pod_id 2>/dev/null || true)}"
[ -n "$KEY" ] && [ -n "$PID" ] || { echo "usage: down.sh [pod_id] (or /tmp/acp_runpod_pod_id)"; exit 1; }
curl -s -X POST "https://api.runpod.io/graphql?api_key=$KEY" -H 'Content-Type: application/json' \
  -d "{\"query\": \"mutation { podTerminate(input: {podId: \\\"$PID\\\"}) }\"}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("terminated OK" if d.get("data") else f"ERROR: {d}")'
rm -f /tmp/acp_runpod_pod_id
