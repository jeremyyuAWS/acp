# Azure parity: what production runs against what the contract says

PRD §21 phase 3 asks to *"rebuild the current Azure deployment using the common contract"* and to
*"prove feature and performance parity"*. Neither is possible without first writing down what the
current deployment does — so this is that baseline, and the comparison against the contract.

The table below the markers is **generated** from `deploy/public/*.sh` and the standard-production
deployment document. Change a replica range in `rightsize-production.sh` and this file either
regenerates or `scripts/gen_azure_parity.py --check` fails. Everything above the markers is
authored, because what to *do* about a difference is a decision and a generator should not pretend
to make one.

## The finding that mattered, and the decision taken

**Decided 2026-09-05 by the owner: bring the contract to production.** The standard-production
example now describes the assess tier the way production runs it — `replicas: {min: 5, max: 5}`
and **no `autoscale` block** — so the chart reproduces today's behaviour instead of replacing it.
Autoscaling that tier stays available as a later, measured change; it is not a side effect of a
packaging project.

The finding it settles, kept because the reasoning is what makes the decision reviewable:

**Production does not autoscale the assess tier at all.** It is pinned at five replicas —
`min == max` — and `rightsize-production.sh` says why: *"Assessment and Remediation are
throughput-sensitive batch stages: keep five replicas warm so large runs retain the production
performance baseline."* That is a deliberate operating model, chosen against measured behaviour.
The contract's example described that tier as autoscaling **3–10** on queue depth, and the Helm
chart renders a KEDA `ScaledObject` to make it happen — so adopting the chart as it stood would
not have been a like-for-like rebuild: it would have **replaced a warm pool with an autoscaler**,
on a stage whose latency somebody deliberately traded capacity for. That is what "parity" means as
the PRD uses the word. The other direction may well be better; it is a performance change wearing
a migration's clothes, and it should be measured before it is made.

**What the decision changed, beyond the three rows it closed.** The assess tier's replica ceiling
was the largest single term in the fleet's connection demand. Pinning it takes the worst case from
**518 to 418** connections, and the Azure adapter's Postgres requirement from `max_connections >=
533` to `>= 433` — so a decision about latency also moved the number a server has to be
provisioned to reach. That is the seam working: it is stated once, in the document, and every
generated artefact below follows.

**Two halves of one statement, and either alone is wrong.** `min == max` without removing the
block would leave a scale rule attached to a tier that cannot move — a declaration with no
consequence, which reads as configured on every screen that renders it. Removing the block without
pinning would leave the ceiling describing capacity nothing will ever reach. `values.py` reads the
block's ABSENCE (`autoscaling.enabled = bool(tier.get("autoscale"))`) to render a fixed
`replicaCount` and no `ScaledObject`, so the two fields have to agree for the chart to be right.
`test_azure_parity.py::test_the_assess_tier_stays_pinned_warm` fails if either half is undone,
because the way this decision would be lost is not an argument — it is somebody restoring a
plausible-looking autoscale block and nothing going red.

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
is a 20-connection budget, not an open-ended one.

**This paragraph used to end "the contract has no vocabulary for a per-replica connection pool
today", and that stopped being true without the sentence changing.** `tier.connectionPool` was
added with the Azure adapter, `pool_per_replica` reads it, and `spec.validate` accepts it —
checked by declaring `connectionPool: 2` on all three worker tiers of this very example, which
validates OK and takes worst-case demand from **418 to 100**. The gap is no longer in the
vocabulary; it is that the standard-production example still declines to use it. See the last
section.

## Also worth deciding

**The example's header used to be half true, and now names its own exceptions.** It claimed its
ranges *"mirror the reviewed Azure baseline in `deploy/public/rightsize-production.sh`"*. The CPU
and memory do mirror it exactly — every tier matches. The replica ranges did not, and only one of
the differences (the API floor) was acknowledged there. The header now separates the two claims and
names the exceptions, so a reader is not told the document mirrors production in a respect where it
does not.

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

## The last three ranges, decided together (2026-09-05)

**Decided by the owner: the contract is authoritative, and production overrides are documented
rather than silently tolerated.** Three replica ranges had been carried as *unexplained* since the
baseline was first derived. They are decided here as ONE question, because they are one question:
every replica ceiling is a term in the fleet's worst-case Postgres demand, and that demand is what
a server has to be provisioned to survive. Deciding them one at a time is how a capacity budget
gets spent without anyone noticing.

**Priced first, argued second.** Measured with `acpctl`'s own `connection_budget` against this
document:

| change | worst-case connections | headroom (700 server, less 15 reserved) |
|---|---:|---:|
| the contract as it stood | 418 | 267 |
| `api.replicas.max` 4 → 3 | 402 | 283 |
| `discover.replicas.max` 3 → 2 | 400 | 285 |
| `remediate.replicas.min` 3 → 5 | **418** | **267** |

**The floor is free and the ceilings are cheap.** `connection_budget` sums each tier's demand at
MAX replicas, because every replica holds its own pool — so raising the remediate FLOOR moves the
worst case by exactly nothing, and the two ceilings cost 16 and 18 connections against 267 of
headroom. That is the whole reason these could be settled on their merits: none of them is a
capacity problem, so none of them had to be traded against another.

**`remediate.replicas.min`: 3 → 5, the contract adopts production.** `rightsize-production.sh`
names this tier in the same sentence as assess — *"Assessment and Remediation are
throughput-sensitive batch stages: keep five replicas warm so large runs retain the production
performance baseline."* The owner already carried that operating model into the contract for
assess. A contract that accepted the reasoning for one tier and contradicted it for the other was
not describing a considered position, it was describing two different days. The autoscale block
stays, unlike assess, because production really does autoscale this tier.

**`api.replicas.max`: stays 4, production is the override.** Production's ceiling of 3 was chosen
against a floor of 1, and its comment — *"The web tier retains burst headroom"* — is a statement
about the RANGE rather than the ceiling. The contract corrects that floor to 2 for the profile, so
holding the ceiling at 3 would quietly halve the burst range production says it wants, from 3x to
1.5x. 2–4 keeps it at 2x.

**`discover.replicas.max`: stays 3, production is the override.** Production runs 1–2 and records
no reason for the ceiling; its only comment on this tier is about a scale rule, and that rule is
itself listed below as unverifiable from this repository. An unexplained 2 is not evidence of a
considered 2, and the contract does not defer to it.

**What this does NOT claim.** Three real differences remain — the API floor, the API ceiling and
the discovery ceiling — and every one of them is deliberate. The report's flag was called `parity`
and computed as "nothing unexplained"; closing these rows would have flipped it True for the first
time and made the document assert equality it does not have. It is `noUnexplainedDifferences` now,
beside a `stillDiffers` count, because an acknowledgement records why a difference exists and does
not remove it.

**The dominant term is not on this list, and is not settled here.** The contract declares
`maxConnections: 700` and does not pin `connectionPool`; production runs a **150**-connection
server with `ACP_DB_MAX_CONN=2` on every worker tier (#1370). Measured both ways: the contract's
own ranges need 418 connections unpinned, and **100** with the pools pinned as production pins
them — inside a 150-connection server with 35 to spare. So the contract does not need a
700-connection server; it needs to say that it pins pools. That is a larger decision than these
three ranges and is left for the owner rather than folded in here.

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
| `assess` | 2.0 | 4Gi | 5–5 | no |
| `discover` | 1.0 | 2Gi | 1–3 | yes |
| `remediate` | 2.0 | 4Gi | 5–10 | yes |

## Differences

**0 unexplained**, 3 acknowledged.

Every difference now carries a recorded decision. Production still differs from the contract in **3** places — that is the point of the acknowledgements, not something they undo. Each row below says which side is authoritative and why.

| Tier | Field | Azure | Contract | | Why |
|---|---|---|---|---|---|
| `api` | `replicas.min` | `1` | `2` | acknowledged | The example raises the API floor from 1 to 2 because the standard profile requires two API replicas (PRD S8), and the example's own header says so. Azure runs 1 — so today's production would FAIL its own profile's floor, which is a finding about the deployment rather than about the contract. |
| `api` | `replicas.max` | `3` | `4` | acknowledged | Production's ceiling of 3 was chosen against a floor of 1 — rightsize-production.sh says 'The web tier retains burst headroom', which is a statement about the RANGE. The contract corrects that floor to 2 for the profile, so holding the ceiling at 3 would silently halve the burst range production says it wants (3x down to 1.5x); 2-4 keeps it at 2x. Priced: the extra replica is 16 Postgres connections against 267 of headroom. The contract stands and Azure's ceiling is the override to correct alongside its floor. |
| `discover` | `replicas.max` | `2` | `3` | acknowledged | Production runs 1-2 and records no reason for the ceiling — rightsize-production.sh's only comment on this tier ('Discovery can use its existing CPU scale rule') is about the scale rule, and that rule is itself UNVERIFIABLE from this repository. An unexplained 2 is not evidence of a considered 2. Priced: the third replica is 18 Postgres connections against 267 of headroom. The contract stands as the authoritative range; Azure's ceiling is recorded here as a production override, not as the target. |

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
