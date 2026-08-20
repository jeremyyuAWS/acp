# ADR 0039 — Regional resilience & failover strategy

Status: **Proposed** (design + one verified finding; no infra change)
Date: 2026-08-20
Related: ADR 0022 (provider seam + vision fallback floor), ADR 0027 (GPU vision lane),
`api/ai.py:_vision_generate`, `api/providers.py:active_vision_provider`/`local_vision_provider`,
the `/readyz` readiness surface (#487), `scripts/preflight.py` (#450).

## Context

ACP today is a **single-customer PHI pilot** (UTSW). The topology is already partially cross-region:
`acp-app` runs in **East US 2**; the vision GPU (`acp-ollama-gpu`, a single warm T4, `min=max=1`
replica) runs in **West US 2**. The question raised: should we build a multi-region fallback so GPUs /
services keep working if a region fails?

The answer has to distinguish **failure domains** — they have very different blast radius, cost, and
difficulty — and it has to be grounded in what the code *actually* does on failure, not what we assume.

### Verified current-state finding (tested, not assumed)

A behavioral test of the vision fallback (`ADR 0022`) was run against the real provider-selection code
(`api/providers.py`, `api/ai.py`), faking the provider responses (no network):

- **Current production topology** — active provider = `ollama`, `OLLAMA_BASE_URL` = the West US 2 GPU.
  When the GPU is unreachable, `_vision_generate` returns **`None`** → the finding **defers to a human**.
  **No CPU fallback draft is produced.** The fallback branch is gated on `active provider != "ollama"`,
  so it is skipped whenever the active provider *is* ollama (which it is in prod).
- **RunPod topology** — active = a distinct GPU provider that fails, *plus* a separate local Ollama:
  the fallback **does** engage and returns a degraded draft.
- **Why the difference:** `local_vision_provider()` is built from `OLLAMA_BASE_URL`. In the cloud that
  URL *is* the GPU, so the "local CPU floor" is the **same endpoint** — not an independent CPU. The
  floor is only real when `OLLAMA_BASE_URL` points at a genuinely separate local Ollama (the
  keyless/self-hosted topology).

**Conclusion:** in the current cloud config there is **no vision redundancy**. A GPU/region outage
degrades **safely** (human review carries the load; nothing fabricated, no broken scan) but **not to a
CPU draft**. This corrects an earlier informal claim that a GPU outage "falls back to CPU."

Two facts bound the blast radius and make this acceptable as a pilot posture:
- The GPU serves **only** vision alt-text (SC 1.1.1). **Assessment/scanning is pure CPU** — a GPU
  outage does not stop discovery, assessment, or the non-vision remediations.
- Degradation is safe-by-design (defer-to-human), consistent with the "never fabricate alt" rule.

## Decision

Adopt **tiered, phased, PHI-constrained graceful degradation** — **not** full active-active
multi-region — sized to a pilot and grown by failure domain, cheapest-and-most-likely first.

### Tier 1 — Vision / GPU (stateless, degradable)
Already degrades safely (defer-to-human). This is the cheapest tier to make *redundant* if vision
*availability* becomes a requirement, via **one** of:
- bake a genuinely separate **CPU Ollama into the app container** as a real floor (so the ADR-0022
  fallback has somewhere independent to go), or
- stand up a **second warm GPU endpoint** in another compliant region, health-probe-selected.
Neither exists today; do this only when the pilot SLA asks for vision availability, not before.

### Tier 2 — App / compute (near-stateless)
Do the **availability-zone** fix first: a *single-AZ* outage is far more likely than a whole-region
one, and Container Apps covers it cheaply with **zone redundancy + ≥2 replicas** within the region.
The GPU's `min=max=1` is a literal SPOF; the app should not share that shape. **Multi-region app
failover (Front Door + standby) is deferred** — a bigger lift than the risk warrants for a pilot.

### Tier 3 — Data / state (stateful)
**Defer.** Cross-region replication of the store is where multi-region gets genuinely hard and
expensive (consistency, failover, and PHI residency). For a pilot, **single region + solid backups +
a documented recovery runbook** beats a half-built active-active nobody can confidently fail over.

### Overriding gate — PHI residency
Any failover region **must** stay inside the customer's compliant geography (US-East for UTSW today).
A failover that spills PHI into a non-approved region is **worse than the downtime it prevents**.
Failover regions are chosen by compliance first, GPU availability second.

## Phased plan

- **Phase 0 (now — no new spend):** this ADR (state the real degradation to the customer as the
  interim SLA); enable **zone redundancy + ≥2 app replicas**; record the GPU as a known SPOF; keep a
  one-page failure/recovery runbook (what degrades, what stays up, how to fail the GPU over by env var).
- **Phase 1 (if vision availability matters):** a *real* vision fallback — a separate in-container CPU
  Ollama **or** a second warm GPU endpoint, selected on the `/readyz` health signal.
- **Phase 2 (production / SLA-driven):** multi-region app + data failover — a scoped project, gated on
  the PHI-residency design, justified by scale/SLA, not by a pilot.

## Consequences

- **Honest interim posture:** a GPU or West-US-2 outage means vision drafting is **degraded (all images
  route to human review), not down**. Scanning and assessment continue. This is defensible for a pilot
  but **must be stated to the customer**, not implied to be seamless.
- **The "CPU fallback floor" must be qualified** wherever it is described: it is topology-dependent and
  **not active** in the current cloud deployment.
- **Cheapest real win is AZ-redundancy + testing the fallback you have** — not a second region.
- No infra is created by this ADR; it sets the strategy and the sequencing.

## Alternatives considered

- **Full active-active multi-region now.** Rejected for a single-customer pilot: high ongoing cost,
  large ops/PHI attack surface, and a resilience level the SLA does not require. Premature.
- **Assume the ADR-0022 CPU floor already covers GPU outage.** Rejected — the behavioral test shows it
  does **not** in the current topology. Designing on the assumption would have shipped a false SLA.
