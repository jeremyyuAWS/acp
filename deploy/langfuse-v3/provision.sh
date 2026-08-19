#!/usr/bin/env bash
# Provision Langfuse v3 on a single Azure VM and bring the stack up. Idempotent-ish: safe to
# re-run; az vm create fails if the VM exists (delete it first for a clean rebuild).
#
# Prereqs: az logged in (`az account show`), access to the resource group below.
#
# Secrets: the Langfuse PROJECT keys + admin password are read from the environment. To reuse the
# keys the ACP app already traces with (so cutover is host-only), source them from the running
# app first — e.g.:
#
#   eval "$(az containerapp show -g mdk-accessibility -n acp-langfuse \
#     --query \"properties.template.containers[0].env[?starts_with(name,'LANGFUSE_INIT_')]\" -o json \
#     | python3 -c 'import json,sys,shlex;[print(f\"export {e[chr(34)+\"name\"+chr(34)]}={shlex.quote(e.get(chr(34)+\"value\"+chr(34)) or chr(34)+chr(34))}\") for e in json.load(sys.stdin)]')"
#
# then run this script. Nothing here writes a secret to disk in the repo.
set -euo pipefail

RG="${RG:-mdk-accessibility}"
VM="${VM:-acp-langfuse-v3}"
DNS_LABEL="${DNS_LABEL:-acp-langfuse-v3}"
REGION="${REGION:-eastus2}"
VM_SIZE="${VM_SIZE:-Standard_D4s_v3}"          # 16 GB — ClickHouse needs headroom
DATA_DISK_GB="${DATA_DISK_GB:-128}"
: "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY:?set LANGFUSE_INIT_PROJECT_PUBLIC_KEY (see header)}"
: "${LANGFUSE_INIT_PROJECT_SECRET_KEY:?set LANGFUSE_INIT_PROJECT_SECRET_KEY (see header)}"
: "${LANGFUSE_INIT_USER_PASSWORD:?set LANGFUSE_INIT_USER_PASSWORD}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FQDN="${DNS_LABEL}.${REGION}.cloudapp.azure.com"

echo "▸ creating VM $VM ($VM_SIZE) in $RG / $REGION → $FQDN"
az vm create -g "$RG" -n "$VM" \
  --image Ubuntu2204 --size "$VM_SIZE" --location "$REGION" \
  --public-ip-address-dns-name "$DNS_LABEL" --public-ip-sku Standard \
  --admin-username azureuser --generate-ssh-keys \
  --os-disk-size-gb 64 --data-disk-sizes-gb "$DATA_DISK_GB" --storage-sku Premium_LRS \
  --nsg-rule SSH -o none
az vm open-port -g "$RG" -n "$VM" --port 80  --priority 900 -o none
az vm open-port -g "$RG" -n "$VM" --port 443 --priority 901 -o none

# Build the on-VM setup script: mount the data disk, install docker, drop compose + Caddyfile +
# .env, and bring the stack up. Runs backgrounded on the VM so run-command returns promptly.
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
sed "s/\${LF_FQDN}/$FQDN/g" "$HERE/Caddyfile.tmpl" > "$TMP/Caddyfile"
cp "$HERE/docker-compose.yml" "$TMP/docker-compose.yml"

cat > "$TMP/setup.sh" <<SETUP
#!/bin/bash
set -e; exec > /var/log/lf3-setup.log 2>&1
DISK=\$(lsblk -dpno NAME,SIZE | awk '\$2 ~ /${DATA_DISK_GB}G/ {print \$1}' | head -1)
if [ -n "\$DISK" ] && ! blkid \${DISK}1 >/dev/null 2>&1; then
  parted -s "\$DISK" mklabel gpt mkpart primary ext4 0% 100%; sleep 3; mkfs.ext4 -F "\${DISK}1"
fi
mkdir -p /mnt/data
grep -q /mnt/data /etc/fstab || echo "\${DISK}1 /mnt/data ext4 defaults,nofail 0 2" >> /etc/fstab
mount -a || true
command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh
mkdir -p /mnt/data/docker
[ -f /etc/docker/daemon.json ] || echo '{"data-root":"/mnt/data/docker"}' > /etc/docker/daemon.json
systemctl enable docker; systemctl restart docker
mkdir -p /opt/langfuse && cd /opt/langfuse
cat > .env <<ENV
LF_FQDN=$FQDN
PG_PW=\$(openssl rand -hex 16)
CH_PW=\$(openssl rand -hex 16)
REDIS_PW=\$(openssl rand -hex 16)
MINIO_PW=\$(openssl rand -hex 16)
SALT=\$(openssl rand -base64 32)
ENCRYPTION_KEY=\$(openssl rand -hex 32)
NEXTAUTH_SECRET=\$(openssl rand -base64 32)
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=$LANGFUSE_INIT_PROJECT_PUBLIC_KEY
LANGFUSE_INIT_PROJECT_SECRET_KEY=$LANGFUSE_INIT_PROJECT_SECRET_KEY
LANGFUSE_INIT_USER_PASSWORD=$LANGFUSE_INIT_USER_PASSWORD
ENV
nohup bash -c 'cd /opt/langfuse && docker compose pull && docker compose up -d' >> /var/log/lf3-setup.log 2>&1 &
echo "compose up backgrounded"
SETUP

echo "▸ uploading compose + Caddyfile + setup, launching on the VM"
# Encode the three files into a launcher and run it via the VM agent (no SSH round-trip needed).
LAUNCH="$TMP/launcher.sh"
{
  echo '#!/bin/bash'; echo 'mkdir -p /opt/langfuse'
  for f in docker-compose.yml Caddyfile; do
    echo "base64 -d > /opt/langfuse/$f <<'B64_$f'"; base64 -i "$TMP/$f"; echo "B64_$f"
  done
  echo "base64 -d > /opt/lf3-setup.sh <<'B64_SETUP'"; base64 -i "$TMP/setup.sh"; echo 'B64_SETUP'
  echo 'nohup bash /opt/lf3-setup.sh >/var/log/lf3-launch.log 2>&1 &'
  echo 'echo launched'
} > "$LAUNCH"
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts @"$LAUNCH" \
  --query "value[0].message" -o tsv

echo "▸ waiting for https://$FQDN/api/public/health (Docker install + image pulls + CH migrations)…"
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://$FQDN/api/public/health" || true)
  [ "$code" = "200" ] && { echo "✓ v3 up: https://$FQDN"; exit 0; }
  sleep 15
done
echo "✗ not up after ~15min — check: az vm run-command invoke -g $RG -n $VM --command-id RunShellScript --scripts 'cd /opt/langfuse && docker compose ps && docker compose logs --tail 40 langfuse-web'"
exit 1
