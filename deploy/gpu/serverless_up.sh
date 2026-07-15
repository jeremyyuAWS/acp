#!/usr/bin/env bash
# Provision a RunPod SERVERLESS vision endpoint (ADR 0022): a vLLM worker serving Qwen2.5-VL over
# an OpenAI-compatible API, workers scale-to-zero (min 0) so there is no idle cost. Prints the
# endpoint id (the durable, non-secret config value the deploy consumes as RUNPOD_ENDPOINT_ID).
#
# Key is read from ~/.zshrc and NEVER printed. Idempotent-ish: reuses a template/endpoint of the
# same name if one already exists. Tunables via env (GPU pool, worker image, model, max workers).
set -euo pipefail
KEY=$(grep -E '^[[:space:]]*export[[:space:]]+RUNPOD_API_KEY=' ~/.zshrc | head -1 | sed -E 's/.*RUNPOD_API_KEY=//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//')
[ -n "$KEY" ] || { echo "NO_KEY"; exit 1; }
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
GQL="https://api.runpod.io/graphql?api_key=$KEY"

NAME="${ACP_SERVERLESS_NAME:-acp-vision}"
IMAGE="${ACP_VLLM_IMAGE:-runpod/worker-v1-vllm:v2.7.0stable-cuda12.1.0}"
MODEL="${ACP_VLLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
GPUIDS="${ACP_SERVERLESS_GPU:-ADA_24,AMPERE_24}"          # RunPod GPU POOL ids (24GB fits a 7B VL); see docs for pools
WMAX="${ACP_SERVERLESS_WORKERS_MAX:-2}"

gql() {  # gql '<mutation/query string>'  → prints raw JSON
  curl -s -H "content-type: application/json" -H "User-Agent: $UA" "$GQL" -d @- <<JSON
{"query": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1")}
JSON
}

# 1) Template — the vLLM worker image + the model + VL flags. isServerless=true. Reuse an existing
#    template of the same name (RunPod rejects duplicate template names) so this is re-runnable.
TPL=$(gql "query { myself { podTemplates { id name } } }" \
  | python3 -c "import sys,json;ts=(json.load(sys.stdin).get('data') or {}).get('myself',{}).get('podTemplates',[]);print(next((t['id'] for t in ts if t['name']=='$NAME-tpl'),''))" 2>/dev/null || true)
if [ -n "$TPL" ]; then
  echo ">> reusing existing template $TPL"
else
echo ">> creating template ($MODEL on $IMAGE) …"
TPL_MUT=$(cat <<GQLM
mutation {
  saveTemplate(input: {
    name: "$NAME-tpl", imageName: "$IMAGE", isServerless: true,
    containerDiskInGb: 25, volumeInGb: 0, dockerArgs: "", ports: "",
    env: [
      {key: "MODEL_NAME", value: "$MODEL"},
      {key: "TRUST_REMOTE_CODE", value: "1"},
      {key: "MAX_MODEL_LEN", value: "8192"},
      {key: "GPU_MEMORY_UTILIZATION", value: "0.95"},
      {key: "ENFORCE_EAGER", value: "1"}
    ]
  }) { id name }
}
GQLM
)
TRESP=$(gql "$TPL_MUT")
TPL=$(echo "$TRESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('data') or {}).get('saveTemplate',{}).get('id') or '')" 2>/dev/null || true)
if [ -z "$TPL" ]; then
  echo "TEMPLATE_FAILED: $(echo "$TRESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('errors') or [{}])[0].get('message','?'))" 2>/dev/null || echo parse-err)"
  echo "   → the vLLM/VL config likely needs tuning; use the RunPod console quick-deploy for a VL model instead (2 min), then pass its endpoint id to deploy as RUNPOD_ENDPOINT_ID."
  exit 2
fi
echo "   template id = $TPL"
fi

# 2) Endpoint — scale-to-zero (workersMin 0), queue-delay autoscale.
echo ">> creating serverless endpoint (min=0, max=$WMAX, gpu=$GPUIDS) …"
EP_MUT=$(cat <<GQLM
mutation {
  saveEndpoint(input: {
    name: "$NAME", templateId: "$TPL", gpuIds: "$GPUIDS",
    workersMin: 0, workersMax: $WMAX, idleTimeout: 5,
    scalerType: "QUEUE_DELAY", scalerValue: 4, locations: "", networkVolumeId: ""
  }) { id name }
}
GQLM
)
ERESP=$(gql "$EP_MUT")
EID=$(echo "$ERESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('data') or {}).get('saveEndpoint',{}).get('id') or '')" 2>/dev/null || true)
if [ -z "$EID" ]; then
  echo "ENDPOINT_FAILED: $(echo "$ERESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('errors') or [{}])[0].get('message','?'))" 2>/dev/null || echo parse-err)"
  exit 3
fi
echo "RUNPOD_ENDPOINT_ID=$EID"
echo "$EID" > /tmp/acp_runpod_serverless_id
echo "OPENAI_URL=https://api.runpod.ai/v2/$EID/openai/v1/chat/completions"
echo ">> pass RUNPOD_ENDPOINT_ID=$EID + the RUNPOD_API_KEY secret to the deploy (Stage 3)."
