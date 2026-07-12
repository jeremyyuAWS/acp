#!/usr/bin/env bash
# Stand up a RunPod GPU pod running ollama, for llava:13b alt-text drafting.
# Key is read from ~/.zshrc and NEVER printed. Only the (non-secret) pod id / proxy URL are echoed.
set -euo pipefail
KEY=$(grep -E '^[[:space:]]*export[[:space:]]+RUNPOD_API_KEY=' ~/.zshrc | head -1 | sed -E 's/.*RUNPOD_API_KEY=//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//')
[ -n "$KEY" ] || { echo "NO_KEY"; exit 1; }
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
GQL="https://api.runpod.io/graphql?api_key=$KEY"

# Try a list of GPU types in order — 4090 worked before; fall through on SUPPLY_CONSTRAINT.
for GPU in "NVIDIA GeForce RTX 4090" "NVIDIA GeForce RTX 3090" "NVIDIA RTX A5000" "NVIDIA A40"; do
  echo ">> trying GPU: $GPU"
  RESP=$(curl -s -H "content-type: application/json" -H "User-Agent: $UA" "$GQL" -d @- <<JSON
{"query":"mutation { podFindAndDeployOnDemand(input: { cloudType: SECURE, gpuCount: 1, gpuTypeId: \"$GPU\", name: \"acp-ollama-gpu\", imageName: \"ollama/ollama:latest\", ports: \"11434/http\", volumeInGb: 40, containerDiskInGb: 40, volumeMountPath: \"/root/.ollama\" }) { id machineId } }"}
JSON
)
  PID=$(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('data') or {}).get('podFindAndDeployOnDemand',{}).get('id') or '')" 2>/dev/null || true)
  if [ -n "$PID" ]; then echo "POD_ID=$PID"; echo "PROXY=https://$PID-11434.proxy.runpod.net"; echo "$PID" > /tmp/acp_runpod_pod_id; exit 0; fi
  echo "   no pod ($(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('errors') or [{}])[0].get('message','?'))" 2>/dev/null || echo parse-err))"
done
echo "ALL_GPU_CONSTRAINED"; exit 2
