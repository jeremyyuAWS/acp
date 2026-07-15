#!/usr/bin/env bash
set -euo pipefail
# Cross-subscription GPU Ollama on a plain GPU VM (fallback for when the "Customer Demos"
# subscription can't host GPU — Microsoft.Compute is NotRegistered there and GPU quota is 0).
#
# Part A provisions a GPU VM + Ollama (llava:13b + llama3.1:8b) in YOUR subscription; Part B
# repoints the East US 2 acp-app (in Customer Demos) at it cross-subscription over an
# IP-restricted endpoint. The app tier does not move — only inference does.
#
# For the durable, scale-to-zero Azure-native path once GPU quota lands in a supported region,
# use deploy/ollama/gpu-runbook.sh (ACA serverless GPU, West US 3) instead.
#
# Every az call is scoped with --subscription (AZ[@] for your sub, "$CD_SUB" for the app) — no
# global `az account set`, so a mid-run failure can't leave your shell repointed.

# ── config (override via env) ────────────────────────────────────────────────
YOUR_SUB="${ACP_GPU_SUB:-}"                       # REQUIRED: your subscription id or name
LOC="${ACP_GPU_LOC:-eastus2}"                     # a region where YOU have NCasT4_v3 quota
RG="${ACP_GPU_RG:-acp-gpu-rg}"
VM="${ACP_GPU_VM:-acp-ollama-gpu}"
VM_SIZE="${ACP_GPU_VM_SIZE:-Standard_NC4as_T4_v3}"  # 1x T4 (16GB VRAM), 4 vCPU. NC8as_T4_v3 = more CPU.
ADMIN="${ACP_GPU_ADMIN:-azureuser}"
VISION_MODEL="${ACP_VISION_MODEL:-llava:13b}"
TEXT_MODEL="${ACP_TEXT_MODEL:-llama3.1:8b}"
CD_SUB="${ACP_APP_SUB:-AZLABSV2.0-Sandbox(POC)}"  # subscription the app lives in
APP_RG="${ACP_APP_RG:-mdk-accessibility}"
APP="${ACP_APP:-acp-app}"

if [ -z "$YOUR_SUB" ]; then
  echo "set ACP_GPU_SUB to your subscription id/name first (export ACP_GPU_SUB=...)." >&2
  exit 1
fi
AZ=(--subscription "$YOUR_SUB")

# ══ PART A — GPU VM + Ollama in YOUR subscription ════════════════════════════
echo "== A1/5 prereqs: register Microsoft.Compute + show T4 quota =="
az provider register "${AZ[@]}" -n Microsoft.Compute --wait
# If the create below fails on quota, request an NCasT4_v3 increase in Portal -> Quotas ($LOC).
az vm list-usage "${AZ[@]}" -l "$LOC" -o table \
  --query "[?contains(localName,'T4')].{n:localName,cur:currentValue,lim:limit}" || true

echo "== A2/5 resource group + GPU VM (Ubuntu 22.04, $VM_SIZE in $LOC) =="
az group create "${AZ[@]}" -n "$RG" -l "$LOC" -o none
az vm create "${AZ[@]}" -g "$RG" -n "$VM" \
  --image Ubuntu2204 --size "$VM_SIZE" \
  --admin-username "$ADMIN" --generate-ssh-keys --public-ip-sku Standard -o none

echo "== A3/5 NVIDIA driver extension (takes ~10-15 min, may reboot) =="
az vm extension set "${AZ[@]}" -g "$RG" --vm-name "$VM" \
  --name NvidiaGpuDriverLinux --publisher Microsoft.HpcCompute --version 1.6 -o none

VM_IP="$(az vm show "${AZ[@]}" -g "$RG" -n "$VM" -d --query publicIps -o tsv)"
echo "   VM public IP: $VM_IP"

echo "== A4/5 lock SSH to your current IP =="
MY_IP="$(curl -s ifconfig.me)"
az network nsg rule update "${AZ[@]}" -g "$RG" --nsg-name "${VM}NSG" \
  --name default-allow-ssh --source-address-prefixes "$MY_IP" -o none 2>/dev/null || true

echo "== A5/5 wait for the GPU driver, then install Docker + NVIDIA toolkit + Ollama =="
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
# poll until the driver is up (the extension can take a while / reboot the box)
for i in $(seq 1 30); do
  if ssh "${SSH_OPTS[@]}" "$ADMIN@$VM_IP" 'nvidia-smi -L' >/dev/null 2>&1; then break; fi
  echo "   ...waiting for GPU driver (attempt $i)"; sleep 30
done
ssh "${SSH_OPTS[@]}" "$ADMIN@$VM_IP" "VISION='$VISION_MODEL' TEXT='$TEXT_MODEL' bash -s" <<'REMOTE'
  set -e
  nvidia-smi -L || { echo "GPU driver still not ready — re-run this step once the extension finishes"; exit 1; }
  command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
  if ! dpkg -l nvidia-container-toolkit >/dev/null 2>&1; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https#' \
      | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
  fi
  sudo docker rm -f ollama 2>/dev/null || true
  sudo docker run -d --name ollama --gpus all --restart unless-stopped \
    -p 11434:11434 -e OLLAMA_MAX_LOADED_MODELS=2 -v ollama:/root/.ollama ollama/ollama:latest
  for i in $(seq 1 30); do curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 2; done
  sudo docker exec ollama ollama pull "$TEXT"
  sudo docker exec ollama ollama pull "$VISION"
  sudo docker exec ollama ollama list
REMOTE

# ══ PART B — allowlist the app's egress + repoint (Customer Demos) ═══════════
echo "== B1/2 open 11434 to ONLY the app's egress IPs (Ollama has no auth) =="
EGRESS="$(az containerapp show --subscription "$CD_SUB" -g "$APP_RG" -n "$APP" \
  --query "properties.outboundIpAddresses" -o tsv)"
echo "   app egress IPs: $EGRESS"
p=1100
for ip in $EGRESS; do
  az network nsg rule create "${AZ[@]}" -g "$RG" --nsg-name "${VM}NSG" \
    --name "ollama-${ip//./-}" --priority "$p" --access Allow --protocol Tcp \
    --destination-port-ranges 11434 --source-address-prefixes "$ip" -o none
  p=$((p+1))
done

echo "== B2/2 repoint $APP at the GPU VM =="
# NOTE: http:// is unencrypted over the internet (mitigated by the IP allowlist). For real use,
# front the VM with Caddy (auto-HTTPS on a domain) or a Cloudflare Tunnel and use https here.
az containerapp update --subscription "$CD_SUB" -g "$APP_RG" -n "$APP" \
  --set-env-vars "OLLAMA_BASE_URL=http://${VM_IP}:11434" \
                 "OLLAMA_VISION_MODEL=${VISION_MODEL}" \
                 "OLLAMA_MODEL=${TEXT_MODEL}" -o none

echo
echo "Done. Endpoint: http://${VM_IP}:11434"
curl -s "http://${VM_IP}:11434/api/tags" | head -c 400; echo
echo "Verify: run a scan with an image in the app, check Langfuse for vision latency (GPU ~1-3s)."
echo "Save cost when idle: az vm deallocate ${AZ[*]} -g $RG -n $VM   (models persist; az vm start to resume)."
echo "Rollback: re-run B2 with the original in-Azure Ollama FQDN + OLLAMA_VISION_MODEL=moondream."
