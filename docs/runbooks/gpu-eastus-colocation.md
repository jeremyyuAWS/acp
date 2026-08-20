# Runbook — co-locate the ACP GPU in the US-East geography

**Goal:** eliminate the cross-region PHI movement and the `zone: cloud` reading caused by the GPU
running in **West US 2** while `acp-app` runs in **East US 2**.

**Status:** plan (no infra created). Verified against the live Azure subscription
`AZLABSV2.0-Sandbox(POC)` (`8fab0f8f-…`) on 2026-08-20.

## Decision (2026-08-20): **Path A**

The co-location approach is **Path A** — GPU in **East US** on **external ingress** — which fixes the
cross-country egress and latency while `zone` remains `cloud`. **Path B is not pursued.** Per
**ADR 0039**, the temporary pilot explicitly accepts `zone: cloud` / single-region risk, so Path B's
app relocation to earn a `zone: local` badge is unwarranted for the pilot; a `zone: local` design
belongs to the customer-production contract, against the customer's SLA. Path A is model-agnostic — the
same pattern deploys the T4 today and the A100 later (pending Deva + a production subscription), changing
only the image and the workload-profile type.

---

## Key finding from the pre-flight checks (this corrects the first draft)

Azure Container Apps **does not offer any GPU workload profile in East US 2** in this subscription —
supported profiles there are `D4 D8 D16 D32 E4 E8 E16 E32 Consumption Flex` only. So the app's own
region cannot host the managed GPU. The `NCASv3_T4` **VM** quota (0/20 in East US 2) is real but is for
VMs/AKS, not the Container Apps GPU profile.

Regions that DO offer the managed T4 profile (`Consumption-GPU-NC8as-T4`):
**East US, West US 2, West US 3, South Central US** (East US also offers `NC24-A100`).

**Therefore the viable co-location target is East US** — a different Azure region from the app, but the
**same US-East geography** (intra-geo, single-digit-ms latency, same data-residency area) — a decisive
improvement over the cross-country West US 2 hop.

## The `zone` nuance (don't conflate with region)

`ai.provenance()` / `providers.zone_for_url` return `local` only when the GPU endpoint is a
private/internal host (localhost, private IP range, `.internal`), never for a public
`*.azurecontainerapps.io` FQDN. The GPU reads `cloud` today because it uses **external** ingress. So:

- Moving the GPU to East US with **external ingress** → fixes the cross-country egress and latency, but
  `zone` stays `cloud` (public endpoint).
- Getting `zone: local` → requires the GPU on **internal ingress in the same Container Apps environment
  as the app**, or a **VNet + private DNS** so the host resolves to a private/internal name.

## Live GPU being mirrored

| | Value |
|---|---|
| Image | `mdkaccessibilityacr.azurecr.io/acp-ollama:gpu-llava13b-llama31-v2` (models baked in) |
| Profile (WUS2) | dedicated `t4` = Standard_NC8as_T4_v3 (8 vCPU / 56 GiB / 1× T4 16 GB), warm min=max=1 |
| Ingress | external, port 11434 |
| App | `acp-app`, RG `mdk-accessibility`, East US 2; endpoint var **`OLLAMA_BASE_URL`** |
| ACR | `mdkaccessibilityacr.azurecr.io` |

> Note: East US offers the **Consumption** GPU profile (serverless, scale-to-zero capable), not a
> *dedicated* `t4` profile. Keep it warm with `--min-replicas 1`; allow scale-to-zero for lower idle
> cost at the price of cold starts.

---

## Path A — GPU in East US, external ingress (simplest; same-geo; `zone` stays `cloud`)

```bash
RG=mdk-accessibility
ENV=acp-gpu-eus                     # new East US CA environment
az containerapp env create -n $ENV -g $RG -l eastus --logs-destination none
az containerapp env workload-profile add -n $ENV -g $RG \
  --workload-profile-name gpu --workload-profile-type Consumption-GPU-NC8as-T4

az containerapp create -n acp-ollama-gpu-eus -g $RG --environment $ENV \
  --image mdkaccessibilityacr.azurecr.io/acp-ollama:gpu-llava13b-llama31-v2 \
  --workload-profile-name gpu --cpu 8 --memory 56Gi \
  --min-replicas 1 --max-replicas 1 \
  --ingress external --target-port 11434 \
  --registry-server mdkaccessibilityacr.azurecr.io          # + MI/creds as the WUS2 app uses

NEW=$(az containerapp show -n acp-ollama-gpu-eus -g $RG \
      --query properties.configuration.ingress.fqdn -o tsv)
curl -s https://$NEW/api/tags        # expect llama3.1:8b + llava:13b

az containerapp update -n acp-app -g mdk-accessibility \
  --set-env-vars OLLAMA_BASE_URL=https://$NEW
```
**Outcome:** cross-country egress gone, latency down; `/config` still shows `zone: cloud` (public host).

## Path B — true `zone: local` (GPU on internal ingress, app + GPU in one East US env)

Same as Path A but: create the GPU with `--ingress internal`, and run `acp-app` in the **same** East US
environment so it reaches the GPU over the internal name `https://acp-ollama-gpu-eus.internal.<env>…`.
This makes `zone_for_url` return `local`. Cost: relocating `acp-app` to an East US environment (DNS,
custom domain, cert re-point) — a larger change than Path A. Choose B only if a `zone: local` badge is a
contractual requirement rather than the egress/latency fix.

## Validation
```bash
curl -s https://acp-app.greenwater-4bf2c997.eastus2.azurecontainerapps.io/config \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['ai'])"
# Path A → zone=cloud, host=…eastus…; Path B → zone=local
```
Then one signed-in vision remediation → confirm the trace's `processing_zone` (this is the live GPU
proof; needs an authorized sign-in).

## Rollback
One env var: `az containerapp update -n acp-app -g mdk-accessibility --set-env-vars OLLAMA_BASE_URL=https://acp-ollama-gpu.purplebeach-80e1296b.westus2.azurecontainerapps.io`.
Keep the West US 2 GPU running until the East US one is validated, then
`az containerapp delete -n acp-ollama-gpu -g mdk-accessibility`.

## Cost
Consumption-GPU-NC8as-T4 warm 24/7 ≈ **$550–1,100/mo** (confirm exact East US rate). Scale-to-zero cuts
idle cost but reintroduces cold starts. You pay for both GPUs briefly during validation.

## Open decisions before running
1. **Path A (same-geo egress fix, `zone: cloud`) vs. Path B (true `zone: local`, app relocation).**
2. **Warm (min-replicas 1) vs. scale-to-zero** (cost vs. cold-start).
3. **Confirm Consumption-GPU quota** for East US in this subscription (profile is supported; quota is a
   separate `az quota` check — serverless GPU has its own quota bucket, distinct from the NCASv3_T4 VM
   family).
4. **Data-residency check:** confirm East US is acceptable for UTSW PHI (both East US 2 and East US are
   US-East geography; verify against the customer's residency terms).

## Pre-flight results (verified 2026-08-20)
- East US 2 GPU workload profile: **none** (plan-breaking for the original East-US-2 idea).
- East US GPU profile: **`Consumption-GPU-NC8as-T4` + `NC24-A100` present.**
- `acp-app`: RG `mdk-accessibility`, East US 2; repoint var `OLLAMA_BASE_URL`.
- Live GPU image/profile mirrored above from `acp-ollama-gpu` (RG `mdk-accessibility`, WUS2).
