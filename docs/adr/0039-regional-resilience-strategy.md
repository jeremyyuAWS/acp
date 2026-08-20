# ADR 0039 — Regional resilience & failover strategy

Status: **Accepted** — pilot posture set 2026-08-20 (revised to distinguish pilot vs. customer-production contracts)
Date: 2026-08-20
Related: ADR 0022 (provider seam + vision fallback floor), ADR 0027 (GPU vision lane),
job retry + dead-letter (#347), `api/ai.py:_vision_generate`,
`api/providers.py:active_vision_provider`/`local_vision_provider`, `/readyz` (#487),
`scripts/preflight.py` (#450).

## Context

ACP runs under **two very different infrastructure contracts**, and conflating them is the error this
ADR exists to prevent:

- the **temporary pilot** — a Movate-hosted, cost-optimized environment for a single customer (UTSW), and
- **customer production** — a future customer-controlled Azure environment governed by the customer's SLA.

Resilience decisions that are correct for one are wrong for the other. The question raised — "should we
build multi-region / cross-AZ failover?" — has to be answered *per contract*, and grounded in what the
code actually does on failure.

### Verified current-state finding (tested, not assumed)

A behavioral test of the vision fallback (`ADR 0022`) was run against the real provider-selection code
(no network, faked responses):

- **Current topology** — active provider `ollama`, `OLLAMA_BASE_URL` = the GPU. GPU unreachable →
  `_vision_generate` returns **`None`** → the finding **defers to a human**. **No CPU fallback draft.**
  The fallback branch is gated on `active provider != "ollama"`, so it is skipped in prod.
- The CPU floor only engages with a *distinct* GPU provider **plus** a genuinely separate local Ollama;
  `local_vision_provider()` is built from the same `OLLAMA_BASE_URL`, which in the cloud *is* the GPU.

**Conclusion:** there is no vision redundancy today. A GPU outage degrades safely (defer-to-human;
nothing fabricated; scan not broken) but not to a CPU draft. This corrects an earlier informal claim.

## Two deployment contracts

| Pilot environment | Customer production |
|---|---|
| Temporary Movate-hosted environment | Customer-controlled Azure environment |
| Cost-optimized, single-region | Zone-redundant App and Worker |
| A100 is a degradable dependency | GPU continuity designed to customer SLA |
| Manual recovery acceptable | Tested automated recovery |
| Backups and runbook | Zone-resilient PostgreSQL, Redis and Blob |
| No cross-AZ SLA | Availability defined by customer requirements |
| PHI controls still mandatory | Customer residency and security policies govern |

## Decision

> For the temporary pilot, ACP accepts single-region and single-zone infrastructure risk while
> preserving functional safety: infrastructure failures may interrupt service or route vision-dependent
> remediation to human review, but they must never fabricate evidence or produce an accessibility PASS.
> Cross-AZ availability and stateful-service redundancy are deferred to the customer-hosted production
> deployment, where they will be designed against the customer's SLA, RTO, RPO and PHI-residency
> requirements.

### Pilot posture (explicit)
- **Single-region** App, Worker, and data services (App/Worker/data in East US 2; the A100 vision
  service in East US — same US-East geography; the A100 is a *degradable* dependency, so its separation
  is acceptable).
- **One East US A100** vision service. *(Interim until A100 is provisioned: the existing West US 2 T4 —
  A100 is `0/0` quota on the current sandbox subscription and requires Deva's approval + a production
  subscription; see the GPU co-location runbook.)*
- **A100 failure → affected vision drafts defer to humans.** Discovery, assessment, and deterministic
  remediation continue.
- **Durable jobs retry safely** after transient compute failures (retry + dead-letter, #347).
- **Backups plus a documented manual-recovery procedure** (`docs/runbooks/failure-recovery.md`).
- **No promise of uninterrupted service** during an AZ or regional outage.
- **PHI controls remain mandatory.**
- **Cross-AZ availability and stateful-service redundancy are explicitly deferred** — *not* partially
  engineered now.

### Customer production (deferred design — built against the customer's requirements)
- **Zone-redundant App and Worker.**
- **GPU continuity designed to the customer SLA.**
- **Tested automated recovery.**
- **Zone-resilient PostgreSQL, Redis, and Blob.**
- **Availability defined by customer requirements** (SLA / RTO / RPO).
- **Customer residency and security policies govern.**

## The honest failure statement

**Vision failures degrade; core-infrastructure failures may cause temporary downtime.**

- **GPU / A100 failure** → vision drafting degrades: affected images route to human review; the system
  stays up; scanning, assessment, and deterministic remediation continue.
- **App / PostgreSQL / regional failure** → the pilot may be **temporarily unavailable**; recovery is via
  backups + the documented manual procedure. This is acceptable and expected for a temporary pilot, and
  **must be stated to the customer** — not implied to be seamless.

In **every** failure mode the functional-safety invariant holds, independent of infrastructure: ACP
**never fabricates evidence and never emits a false accessibility PASS.** Degradation is always toward
*more* human involvement, never toward an unearned green.

## Consequences

- The pilot's availability posture is honest and defensible: functional safety is absolute; uptime is
  best-effort single-region. The distinction from customer production is documented, so no one carries a
  pilot assumption into a production SLA (or vice versa).
- The "CPU fallback floor" must be qualified wherever described — topology-dependent, not active in the
  current cloud config.
- Customer-production HA (zone redundancy, stateful replication, automated recovery) is a **separate,
  SLA-driven project**, deferred here on purpose.

## Alternatives considered

- **Partially engineer cross-AZ resilience in the pilot now** (enable zone redundancy + ≥2 replicas).
  **Rejected in this revision:** for a temporary Movate-hosted pilot it is premature cost/complexity;
  explicit deferral to the customer-production contract is cleaner and more honest.
- **Full active-active multi-region now.** Rejected — a resilience level the pilot SLA does not require,
  with a large PHI attack surface.
- **Assume the ADR-0022 CPU floor covers GPU outage.** Rejected — the behavioral test shows it does not
  in the current topology; designing on the assumption would ship a false SLA.
