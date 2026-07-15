#!/usr/bin/env bash
set -euo pipefail
# One-time provisioning of GPU-backed Ollama in West US 3.
#
# WHY West US 3: ACA serverless GPU is NOT offered in East US 2 (where the rest of the stack
# lives — the region only exposes CPU D/E profiles). West US 3 offers Consumption-GPU-NC8as-T4
# (T4, scales to zero) and Consumption-GPU-NC24-A100. The API app calls this cross-region over
# OLLAMA_BASE_URL; inference is seconds, so the ~60ms hop + tiny egress are negligible.
#
# PREREQUISITE: the West US 3 NCasT4_v3 GPU vCPU quota must be GRANTED first (defaults to 0 —
# request it in Azure Portal -> Quotas). This script fails fast at env-profile-add if it isn't.
#
# This ADDS a new env + Ollama app and repoints the existing API app; it does not touch the
# CPU Ollama image (deploy/ollama/Dockerfile) — this uses Dockerfile.gpu.
#
# Subscription scoping: like deploy.sh, every az call is scoped with "${AZ[@]}" and this script
# NEVER runs `az account set` — so a mid-run failure can't leave the operator's shell repointed
# at the demo subscription (the footgun tests/test_az_subscription_scope.py guards against).

# ── config ──────────────────────────────────────────────────────────────────
SUB="${ACP_SUBSCRIPTION:-AZLABSV2.0-Sandbox(POC)}"
AZ=(--subscription "$SUB")                       # scope EVERY az call; no global mutation
RG="${ACP_RG:-mdk-accessibility}"                # RGs are region-agnostic; reuse the existing one
ACR="${ACP_ACR:-mdkaccessibilityacr}"            # existing ACR (East US 2); cross-region pull is fine
GPU_REGION="${ACP_GPU_REGION:-westus3}"
GPU_ENV="${ACP_GPU_ENV:-acp-gpu-env-wus3}"
GPU_PROFILE_NAME="gpu-t4"
GPU_PROFILE_TYPE="${ACP_GPU_PROFILE:-Consumption-GPU-NC8as-T4}"  # A100 = Consumption-GPU-NC24-A100
OLLAMA_APP="${ACP_OLLAMA_APP:-acp-ollama-gpu}"
APP="${ACP_APP:-acp-app}"                        # existing East US 2 API app to repoint
VISION_MODEL="${ACP_VISION_MODEL:-llava:13b}"    # replaces 'moondream' (see Dockerfile.gpu VRAM note)
TEXT_MODEL="${ACP_TEXT_MODEL:-llama3.1:8b}"
TAG="gpu-$(date +%s)"

az extension add --name containerapp --upgrade -y >/dev/null 2>&1 || true

# ── 1. West US 3 workload-profiles env + serverless-GPU profile ───────────────
echo "== 1/6 create GPU env + profile in $GPU_REGION =="
az containerapp env create "${AZ[@]}" -g "$RG" -n "$GPU_ENV" -l "$GPU_REGION" --enable-workload-profiles -o none
az containerapp env workload-profile add "${AZ[@]}" -g "$RG" -n "$GPU_ENV" \
  --workload-profile-name "$GPU_PROFILE_NAME" --workload-profile-type "$GPU_PROFILE_TYPE" -o none

# ── 2. build the GPU Ollama image (stronger VLM baked in) ─────────────────────
echo "== 2/6 build acp-ollama:$TAG from Dockerfile.gpu =="
az acr build "${AZ[@]}" -r "$ACR" -t "acp-ollama:${TAG}" -f deploy/ollama/Dockerfile.gpu deploy/ollama -o none

# ── 3. Ollama Container App on the GPU profile ───────────────────────────────
echo "== 3/6 create $OLLAMA_APP on $GPU_PROFILE_NAME =="
ACRSERVER="$(az acr show "${AZ[@]}" -n "$ACR" --query loginServer -o tsv)"
ACRUSER="$(az acr credential show "${AZ[@]}" -n "$ACR" --query username -o tsv)"
ACRPW="$(az acr credential show "${AZ[@]}" -n "$ACR" --query 'passwords[0].value' -o tsv)"
# T4 profile (NC8as_T4_v3) = 8 vCPU / 56Gi / 1x T4. min-replicas 1 keeps the model warm
# (true scale-to-zero would cold-start a multi-GB model load on the first request).
az containerapp create "${AZ[@]}" -g "$RG" -n "$OLLAMA_APP" --environment "$GPU_ENV" \
  --image "$ACRSERVER/acp-ollama:${TAG}" \
  --registry-server "$ACRSERVER" --registry-username "$ACRUSER" --registry-password "$ACRPW" \
  --workload-profile-name "$GPU_PROFILE_NAME" \
  --cpu 8 --memory 56Gi \
  --target-port 11434 --ingress external \
  --min-replicas 1 --max-replicas 2 \
  --env-vars OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_HOST=0.0.0.0:11434 -o none

GPU_FQDN="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$OLLAMA_APP" --query properties.configuration.ingress.fqdn -o tsv)"

# ── 4. lock the Ollama endpoint to the API app's egress (Ollama has NO auth) ──
# Cross-region reachability needs external ingress, so restrict it to acp-app's outbound IPs.
echo "== 4/6 restrict $OLLAMA_APP ingress to $APP egress IPs =="
for ip in $(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" --query "properties.outboundIpAddresses" -o tsv); do
  az containerapp ingress access-restriction set "${AZ[@]}" -g "$RG" -n "$OLLAMA_APP" \
    --rule-name "allow-${ip//./-}" --ip-address "${ip}/32" --action Allow -o none
done

# ── 5. repoint the API app at the GPU Ollama + upgraded vision model ──────────
echo "== 5/6 repoint $APP -> https://$GPU_FQDN ($VISION_MODEL) =="
az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" \
  --set-env-vars "OLLAMA_BASE_URL=https://${GPU_FQDN}" \
                 "OLLAMA_VISION_MODEL=${VISION_MODEL}" \
                 "OLLAMA_MODEL=${TEXT_MODEL}" -o none

# ── 6. verify ────────────────────────────────────────────────────────────────
echo "== 6/6 verify =="
echo "Ollama GPU endpoint: https://${GPU_FQDN}"
curl -s "https://${GPU_FQDN}/api/tags" | head -c 400; echo
echo "Done. Run a scan with an image and check Langfuse for vision latency (GPU ~1-3s vs CPU ~60s)."
echo "Rollback: repoint $APP OLLAMA_BASE_URL back to the in-env CPU Ollama, then delete $OLLAMA_APP + $GPU_ENV."
