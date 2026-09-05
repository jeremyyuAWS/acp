# Azure parity: what production runs against what the contract says

PRD §21 phase 3 asks to *"rebuild the current Azure deployment using the common contract"* and to
*"prove feature and performance parity"*. Neither is possible without first writing down what the
current deployment does — so this is that baseline, and the comparison against the contract.

The table below the markers is **generated** from `deploy/public/*.sh` and the standard-production
deployment document. Change a replica range in `rightsize-production.sh` and this file either
regenerates or `scripts/gen_azure_parity.py --check` fails. Everything above the markers is
authored, because what to *do* about a difference is a decision and a generator should not pretend
to make one.

## The finding that matters

**Production does not autoscale the assess tier at all.** It is pinned at five replicas —
`min == max` — and `rightsize-production.sh` says why: *"Assessment and Remediation are
throughput-sensitive batch stages: keep five replicas warm so large runs retain the production
performance baseline."* That is a deliberate operating model, chosen against measured behaviour.

The contract's standard-production example describes that tier as autoscaling **3–10** on queue
depth, and the Helm chart renders a KEDA `ScaledObject` to make it happen. So adopting the chart
on Azure as it stands would not be a like-for-like rebuild: it would **replace a warm pool with an
autoscaler**, on a stage whose latency somebody deliberately traded capacity for.

That is a decision, and it is the first one phase 3 needs:

- **Bring the contract to production** — record the pinned-warm model in the document (`replicas:
  {min: 5, max: 5}`, no `autoscale` block) so the chart reproduces today's behaviour exactly, and
  treat autoscaling as a later, measured change.
- **Bring production to the contract** — accept that a cold start on the assess tier costs
  latency, and let queue-depth scaling manage it.

The first is what "parity" means as the PRD uses the word. The second may well be better, but it
is a performance change wearing a migration's clothes, and it should be measured before it is
made rather than arriving as a side effect of a packaging project.

### This finding was about two tiers a day ago

Remediate was pinned at `5–5` too, and the paragraph above named both. PR #1370 — *"Autoscale
remediation within the database budget"* — landed while this comparison was being built, and gave
`acp-remediate` a real queue-depth scale rule and a `5–10` range. The tier now autoscales on both
sides, and only its floor still differs (5 against the contract's 3). The finding narrowed; it did
not go away.

Two things about that are worth keeping rather than quietly editing out.

**The change was caught by a test, not by a reader.** `test_the_baseline_found_every_workload_tier`
went red on the merge, because #1370 gave `update_app` a sixth positional argument
(`ACP_DB_MAX_CONN`) and the baseline's anchored regex stopped matching three of the five calls. A
parser that silently finds fewer apps produces a *shorter* table with *fewer* differences — which
reads like progress. The anti-vacuous guard is the only reason it read as a failure instead.

**#1370's scale rule and this repo's Helm chart agree, independently.** The production rule filters
`type IN ('remediate_file','rescore_file','apply_approved_values')`; the chart's KEDA query takes
that same list from `inventory.LANE_JOB_TYPES`. Two people reached the same shape from opposite
ends without coordinating, including the same correction — the `jobs` table has a `type` column and
no `role` column, which is exactly what the chart's first KEDA query got wrong. That agreement is
the strongest evidence available here that the remediate lane's autoscaling signal is right, and it
narrows what a rebuild has to prove for that tier to the replica floor alone.

#1370 also pinned `ACP_DB_MAX_CONN=2` per replica on all three worker tiers, to keep the fleet
under Postgres's measured 150-connection ceiling. The baseline records it, because a replica
ceiling means something different once each replica caps its own pool: `5–10` remediate replicas
is a 20-connection budget, not an open-ended one. The contract has no vocabulary for a per-replica
connection pool today, which is a gap in the document rather than a difference in the deployment.

## Also worth deciding

**The example's header is half true.** It says its ranges *"mirror the reviewed Azure baseline in
`deploy/public/rightsize-production.sh`"*. The CPU and memory do mirror it exactly — every tier
matches. The replica ranges do not, and only one of the differences (the API floor) is
acknowledged in that header. The generated table below lists the rest.

**Today's production fails its own profile's floor.** The standard profile requires two API
replicas (PRD §8); `acp-app` runs `1–3`. The example raises the floor to 2 and says so, which
makes the contract right and the deployment short — a finding about the deployment, not the
document.

**Three deployed apps have no place in the tier model** — Ollama, Grafana and the retired generic
`acp-worker`. The first two are modelled elsewhere in the document (`ai.ollama`,
`observability.grafana`) and are not workload tiers, so their absence from the comparison is
correct. `acp-worker` is different: `deploy.sh` still creates and updates it while `redeploy.sh`
calls it *"the retired generic acp-worker"* and deliberately excludes it from the health gate. One
of those two scripts is wrong about the topology, and it is worth settling which.

## On ADR 0048's Container Apps claims

ADR 0048 rejected per-cloud native runtimes partly because *"ACA specifically has no
PodDisruptionBudget, no NetworkPolicy and an 8Gi Consumption ceiling, so it cannot express three of
the guarantees the regulated and HA profiles are defined by."*

What this repository can confirm is narrower, and the distinction is worth keeping: **nothing in
`deploy/public/` configures a disruption budget or any network policy**, and the largest memory
any app is given is exactly `8Gi` (`acp-ollama`). That is consistent with the ADR and does not
prove it — whether ACA *could* express those things is a question about Azure's API surface, which
cannot be settled from this repository offline. Treat the ADR's claim as a design premise that has
not been contradicted here, not as something this document verifies.

<!-- BEGIN GENERATED: azure-parity -->


_Generated by `scripts/gen_azure_parity.py` from `deploy/public/*.sh` and `packaging/examples/standard-production.acp-deployment.yaml`. Do not edit by hand._

## What Azure actually runs

Parsed from the deployment scripts, not from a live subscription.

| Container app | Tier | CPU | Memory | Replicas | DB pool | Scales? | Ingress | Scale rules | Read from |
|---|---|---:|---:|---|---:|---|---|---|---|
| `acp-app` | `api` | 1.0 | 2Gi | 1–3 | — | yes | external | none in this repo | rightsize-production.sh + deploy.sh |
| `acp-assess` | `assess` | 2.0 | 4Gi | 5–5 | 2 | **no** | none | none in this repo | rightsize-production.sh |
| `acp-discovery` | `discover` | 1.0 | 2Gi | 1–2 | 2 | yes | none | none in this repo | rightsize-production.sh |
| `acp-grafana` | — | 0.5 | 1.0Gi | 1–1 | — | **no** | external | none in this repo | deploy.sh |
| `acp-ollama` | — | 4.0 | 8Gi | 0–1 | — | yes | none | none in this repo | rightsize-production.sh |
| `acp-remediate` | `remediate` | 2.0 | 4Gi | 5–10 | 2 | yes | none | `remediation-queue` | rightsize-production.sh |
| `acp-worker` | — | 2.0 | 4.0Gi | 1–3 | — | yes | none | `jobs-queued` | deploy.sh |

## What the contract describes

| Tier | CPU | Memory | Replicas | Autoscaled |
|---|---:|---:|---|---|
| `api` | 1.0 | 2Gi | 2–4 | yes |
| `assess` | 2.0 | 4Gi | 3–10 | yes |
| `discover` | 1.0 | 2Gi | 1–3 | yes |
| `remediate` | 2.0 | 4Gi | 3–10 | yes |

## Differences

**6 unexplained**, 1 acknowledged.

| Tier | Field | Azure | Contract | | Why |
|---|---|---|---|---|---|
| `api` | `replicas.min` | `1` | `2` | acknowledged | The example raises the API floor from 1 to 2 because the standard profile requires two API replicas (PRD S8), and the example's own header says so. Azure runs 1 — so today's production would FAIL its own profile's floor, which is a finding about the deployment rather than about the contract. |
| `api` | `replicas.max` | `3` | `4` | **unexplained** | — |
| `assess` | `replicas.min` | `5` | `3` | **unexplained** | — |
| `assess` | `replicas.max` | `5` | `10` | **unexplained** | — |
| `assess` | `autoscaled` | `False` | `True` | **unexplained** | — |
| `discover` | `replicas.max` | `2` | `3` | **unexplained** | — |
| `remediate` | `replicas.min` | `5` | `3` | **unexplained** | — |

## Deployed, and not modelled by the contract

| Container app | Why it is out of the tier model |
|---|---|
| `acp-grafana` | observability.grafana in the document, not a workload tier |
| `acp-ollama` | the local model runtime; ai.ollama in the document, not a workload tier |
| `acp-worker` | the retired generic mixed-role worker (redeploy.sh excludes it deliberately) |

## What this comparison cannot see

A clean row above means the SCRIPTS agree with the contract. It does not mean the running estate does.

- **ACP_WORKER_ROLE on assess and remediate** — redeploy.sh states that only acp-discovery's role is set in this repo; the other two get ACP_WORKER_ROLE from container-app environment variables set outside it. Which lane each worker actually serves is therefore a convention this repository cannot verify.
- **acp-discovery scale rule** — rightsize-production.sh says 'Discovery can use its existing CPU scale rule', but no scale rule for acp-discovery exists anywhere in this repository — it was applied outside these scripts. Its trigger, threshold and even its existence cannot be checked from here.
- **live estate drift** — Everything here is what the SCRIPTS configure. An app resized or rescaled by hand in the portal is invisible to this comparison.

<!-- END GENERATED: azure-parity -->
