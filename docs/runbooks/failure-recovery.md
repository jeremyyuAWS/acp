# Runbook — ACP failure & recovery (Phase 0)

Operational guide for what degrades vs. stays up when part of ACP fails, and how to recover.
Companion to **ADR 0039** (regional resilience strategy). Current-state values verified against the
live Azure subscription `AZLABSV2.0-Sandbox(POC)` on 2026-08-20.

## Current topology (verified)

| Component | Where | Shape | Notes |
|---|---|---|---|
| `acp-app` (API + SPA) | East US 2, env `mdk-accessibility-env` | replicas **min 1 / max 3** | env **`zoneRedundant = false`** — a known Phase-0 gap |
| Worker tier | in-process or split (`ACP_WORKERS`) | drains the scan queue | readiness = OR of both tiers |
| Vision GPU | `acp-ollama-gpu`, **West US 2** | **`min=max=1`** (single warm T4) | **SPOF**; serves alt-text only |
| Store / state | East US 2 | single region | backups are the recovery path |

**Load-bearing fact (verified by test — see ADR 0039):** the GPU serves **only** vision alt-text
(SC 1.1.1). **Assessment, discovery, and non-vision remediation are pure CPU** and do not depend on the
GPU. And in the current topology a GPU outage produces **no CPU fallback draft** — affected images
**defer to human review** (safe: nothing fabricated, scan not broken).

## What stays up vs. degrades

| Failure | Scanning / assessment | Vision alt-text drafts | Reviewer workflow |
|---|---|---|---|
| **GPU / West US 2 down** | ✅ unaffected (CPU) | ⚠️ degraded → all images **defer to human** | ✅ works; more manual alt |
| **App single-AZ blip** (env not zone-redundant) | ⚠️ risk of brief outage until replica reschedules | ⚠️ with app | ⚠️ with app |
| **Worker tier down** | ❌ scans don't progress (queue not drained) | n/a | ✅ read-only works; new scans stall |
| **Store/data issue** | ❌ | ❌ | ❌ — recover from backup |

---

## Scenario playbooks

### 1. GPU / vision endpoint down (West US 2)
**Symptom:** vision drafts stop; `/config` `.ai` still names the GPU host; images pile into human review.
**Confirm:**
```bash
curl -s https://acp-ollama-gpu.purplebeach-80e1296b.westus2.azurecontainerapps.io/api/tags   # unreachable?
curl -s https://acp-app.greenwater-4bf2c997.eastus2.azurecontainerapps.io/config | python3 -c "import sys,json;print(json.load(sys.stdin)['ai'])"
```
**Impact:** LOW-MEDIUM. Scanning/assessment continue; only auto-drafted alt text is lost (defers to
humans). No data at risk.
**Recovery options (in order):**
1. **Restart the GPU replica:** `az containerapp revision restart -n acp-ollama-gpu -g mdk-accessibility --revision <active>` (or `az containerapp update … --min-replicas 1` to force a new replica).
2. **Fail over to another vision endpoint** if one exists (Phase 1): repoint the app —
   `az containerapp update -n acp-app -g mdk-accessibility --set-env-vars OLLAMA_BASE_URL=<other-endpoint>`.
   Today there is **no second endpoint**, so this is a Phase-1 capability, not available yet.
3. **Accept degradation:** leave it; reviewers draft alt manually until the GPU returns. This is the
   current designed floor.
**Do NOT:** point `OLLAMA_BASE_URL` at a public model outside the compliant US geography — PHI images
would leave the approved region (worse than the degradation).

### 2. App single-AZ / regional degradation (East US 2)
**Symptom:** the app is slow or unreachable.
**Confirm:** `curl -s …/readyz` (readiness), `curl -s …/healthz` (liveness/provenance).
**Impact:** HIGH — the whole surface. The env is **not zone-redundant today**, so a single-AZ event can
take the app down until a replica reschedules.
**Recovery:**
1. Ensure replicas are scaling: `az containerapp show -n acp-app -g mdk-accessibility --query "properties.template.scale"` (min 1 / max 3 today — consider raising **min to ≥2**).
2. If a full-region event: no standby region exists today. Recovery = wait for the region, or redeploy
   the image to another compliant US region and re-point DNS (manual, not pre-built).
**Pilot stance (per ADR 0039):** single-AZ / regional downtime is an **accepted, explicitly-deferred
risk** for the temporary pilot — zone redundancy and multi-region failover are **customer-production**
deliverables, designed against the customer's SLA/RTO/RPO, not engineered here. Do **not** partially
enable zone redundancy on the pilot; keep the manual redeploy above as the documented recovery.

### 3. Worker tier down
**Symptom:** scans accepted but never progress; `/readyz` `degraded` lists `no_workers` or
`worker_tier_never_started`.
**Impact:** MEDIUM — no new scan completes; existing results and review still readable.
**Recovery:** restart the worker container / confirm `ACP_WORKERS` is set on at least one tier; the
scan-start guard makes the same readiness check, so it will refuse new scans until a tier is alive.

### 4. Store / data issue
**Impact:** HIGH — stateful. This is the tier with no live redundancy (ADR 0039 Tier 3, deferred).
**Recovery:** restore from backup. **Precondition:** confirm a tested backup + restore procedure exists
for the store before the pilot carries real PHI — this is the single most important Phase-0 item after
zone redundancy.

---

## Health signals to watch
| Signal | Endpoint | Tells you |
|---|---|---|
| Liveness + build provenance | `GET /healthz` | is this the expected image, is it up |
| Functional readiness | `GET /readyz` | can it run scans now; `degraded[]` names the fault (`no_workers`, `pdf_engine_missing`); `sources.smb` readiness |
| AI provenance / zone | `GET /config` → `.ai` | which GPU/models, and `zone` (local vs cloud) |
| Estate collapse monitor | `GET /monitor/estate` (keyed) | did the newest scan collapse; backlog size |

## Pilot posture (per ADR 0039 — two contracts)

This is the **temporary Movate-hosted pilot**. Per ADR 0039, cross-AZ availability and stateful-service
redundancy are **explicitly deferred to the customer-hosted production deployment** — they are *not*
partially engineered now. The pilot accepts single-region / single-zone risk while preserving functional
safety. The honest one-line summary:

> **Vision failures degrade; core-infrastructure failures may cause temporary downtime.**
> In every case ACP never fabricates evidence and never emits a false accessibility PASS.

### Accepted pilot risks — deliberately NOT engineered now (customer-production deliverables)
- **App env not zone-redundant** (`zoneRedundant=false`, min 1 replica): a single-AZ or regional event
  can cause **temporary downtime**. Accepted for the pilot; zone-redundant App/Worker belongs to customer
  production.
- **GPU `min=max=1`, single region, no second vision endpoint**: an A100/GPU outage → **defer-to-human**.
  Accepted; GPU-continuity-to-SLA belongs to customer production.
- **Single-region stateful services** (Postgres/Redis/Blob): recovery is via backups, not live
  redundancy. Zone-resilient stateful services belong to customer production.

### Pilot must-haves — genuinely needed now
1. **Tested backup + restore for the store, verified BEFORE real PHI.** *(Highest severity — this is the
   pilot's actual safety net, and it is a pilot deliverable, not a deferred one.)*
2. **Durable job retry after transient failures** (#347) — confirm it is active so a transient compute
   blip does not lose in-flight scans.
3. **This runbook kept current, and a named on-call** who can execute the manual recovery.

## What NOT to do
- Do not repoint any PHI-touching endpoint outside the compliant US geography, even to restore service.
- Do not present "GPU degraded" as an outage — scanning continues; say "alt-text drafting is degraded,
  images route to human review."
- Do not merge a resilience change without confirming the failover target is in-region and tested.
