# Langfuse v3 — self-hosted on an Azure VM

Reproduces the deployed Langfuse **v3** tracing backend, and documents the v2→v3 migration.

## Why v3, and why a VM

The old deployment was `langfuse/langfuse:2` as a single Azure Container App on one Postgres. Its
**Session view hung** on large scans (a 44-document scan = 44 traces × their spans, all rendered at
once). Individual traces loaded fine — the aggregate Session view was the bottleneck.

Langfuse **v3** fixes this by moving the trace store to **ClickHouse** (plus Redis for the queue and
S3/MinIO for event/media blobs) and splitting the app into **web + worker**.

ClickHouse needs real local disk and does **not** run reliably on Azure Container Apps (ACA only
offers Azure Files/SMB mounts, which ClickHouse fights). So the v3 stack runs on a **single Azure
VM** via docker-compose on a Premium data disk — the configuration Langfuse recommends for small
self-hosting. Redis/MinIO/Postgres run in the same compose; Caddy fronts it with automatic
Let's Encrypt TLS on the VM's `*.cloudapp.azure.com` DNS label.

```
                       ┌──────────────── Azure VM (acp-langfuse-v3) ────────────────┐
  acp-app  ─┐          │  caddy(443) → langfuse-web:3 ─┐                            │
            ├─ traces →│                               ├→ postgres  (transactional) │
 acp-worker─┘          │           langfuse-worker:3 ──┼→ clickhouse (trace store)  │
                       │                               ├→ redis      (queue/cache)  │
                       │                               └→ minio      (event blobs)  │
                       └────────── /mnt/data (Premium SSD) holds all volumes ───────┘
```

## Live deployment (as provisioned 2026-08-19)

| | |
|---|---|
| Subscription | `AZLABSV2.0-Sandbox(POC)` |
| Resource group | `mdk-accessibility` |
| VM | `acp-langfuse-v3` · `Standard_D4s_v3` (16 GB) · 128 GB Premium data disk |
| URL | `https://acp-langfuse-v3.eastus2.cloudapp.azure.com` |
| Project | seeded with the **same** `acp-compliance` org/project + `pk`/`sk` the app already used |

The app kept its keys — only `LANGFUSE_HOST` moved. The old v2 app `acp-langfuse` was **deactivated**
(stopped, not deleted) so pre-cutover traces stay recoverable; its data was **not** migrated
(deliberate "start fresh").

## Rebuild from scratch

```bash
# 1. reuse the app's existing project keys so cutover is host-only (see provision.sh header for the
#    exact az one-liner to export LANGFUSE_INIT_* from the running app), or set them yourself:
export LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-…
export LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-…
export LANGFUSE_INIT_USER_PASSWORD='…'

# 2. provision the VM + bring the stack up (waits for /api/public/health = 200)
./provision.sh

# 3. verify keys + ingestion before cutover
FQDN=acp-langfuse-v3.eastus2.cloudapp.azure.com
curl -s -u "$LANGFUSE_INIT_PROJECT_PUBLIC_KEY:$LANGFUSE_INIT_PROJECT_SECRET_KEY" \
  "https://$FQDN/api/public/projects"     # → the acp-compliance project

# 4. cut the apps over (only LANGFUSE_HOST changes)
./cutover.sh "https://$FQDN"
```

## Rollback

v2 stays deactivated but intact. To roll the apps back:

```bash
az containerapp revision activate -g mdk-accessibility -n acp-langfuse \
  --revision "$(az containerapp show -g mdk-accessibility -n acp-langfuse --query properties.latestRevisionName -o tsv)"
./cutover.sh https://acp-langfuse.greenwater-4bf2c997.eastus2.azurecontainerapps.io
```

## Decommission v2 for good

Once you're happy with v3 and don't need the old traces:

```bash
az containerapp delete -g mdk-accessibility -n acp-langfuse --yes
```

## Cost & secrets

- Cost moves from the v2 container app to the VM (D4s_v3 + 128 GB Premium disk + public IP). Stopping
  v2 (done) offsets it. Resize the VM down (`az vm resize`) if trace volume is light.
- **No secrets live in this directory.** Infra passwords are generated per-deploy into the VM's
  `/opt/langfuse/.env`; the project keys + admin password come from the operator's environment.
- Traces carry no document content or raw filenames — see `docs/audit-langfuse-phi.md` and
  `api/lf.py` (redacted labels, structured-only payloads).
