# ADR 0048 — Portable deployment packaging: one Helm release, per-cloud infrastructure adapters

Status: Proposed
Date: 2026-09-04
Phase: 0 of 5 (see `docs/prd-acp-portable-deployment.md` §21) — contract only, no provisioning

## Context

ACP deploys to exactly one place today, and the knowledge of how is spread across bash. The Azure
path is `deploy/public/deploy.sh` (643 lines), `redeploy.sh` (726), `rightsize-production.sh` and
`rollback.sh`; the single-node path is `deploy/compose/docker-compose.yml`. Between them they
encode the whole production topology — four tiers, three worker roles, a split that exists so an
API deploy cannot restart a running scan, a Postgres connection budget, a Blob store, a model
volume, an ingress posture — and none of it is stated anywhere a second platform could read.

A customer asking to run ACP on their own Kubernetes cluster is therefore asking us to
reverse-engineer our own deployment. That is the problem this ADR addresses. It is not that we
lack an AWS module.

Two properties of the current system shape everything below, and both are already true:

- **The tiers are already split.** Production runs `acp-app` at `ACP_WORKERS=0` plus
  `acp-discovery`, `acp-assess` and `acp-remediate`, each restricted by `ACP_WORKER_ROLE`
  (`docs/worker-split.md`; `deploy/public/rightsize-production.sh` carries the reviewed capacity
  baseline). The portable contract does not have to invent a topology — it has to describe one.
- **Migrations are already additive.** ADR 0045 establishes expand/contract with contract
  deferred, which is what makes a deploy rollback safe without a schema rollback. Every statement
  about upgrade and rollback below rests on that and adds nothing to it.

## Decision 1 — Kubernetes and Helm are the portability layer; the clouds are adapters around it

One application package. `platform` selects an **infrastructure adapter** — managed Postgres,
Redis, object storage, the secret backend, ingress and storage classes — and never a different
application package, container runtime or code path.

| | Renders to | Adapter supplies |
|---|---|---|
| `azure` | the Helm release on AKS | Azure Database for PostgreSQL, Managed Redis, Blob, Key Vault |
| `aws` | the Helm release on EKS | RDS, ElastiCache, S3, Secrets Manager |
| `gcp` | the Helm release on GKE | Cloud SQL, Memorystore, Cloud Storage, Secret Manager |
| `kubernetes` | the Helm release on a customer cluster | whatever the customer runs |
| `onprem` | the Helm release, or a single server | self-hosted throughout |
| `compose` | Docker Compose | embedded services, evaluation only |

The alternative — a per-cloud module that stands up that cloud's native container runtime (ACA,
ECS, Cloud Run) — was rejected. It produces three deployment topologies to keep at parity rather
than one, and PRD §22's first guardrail is "do not create separate application forks per cloud".
Container Apps in particular is where the divergence would start: it has no PodDisruptionBudget,
no NetworkPolicy and an 8Gi Consumption memory ceiling (`deploy/ollama/Dockerfile` records the
~9.2GB model pair that ceiling OOM-killed), so an ACA adapter cannot express three of the
guarantees the regulated and HA profiles are defined by.

**This claim is tested, not asserted.** `tests/test_packaging_values.py` renders the same workload
for four platforms and requires the application half of the Helm values (`api`, `workers`,
`migrations`, `preflight`, `networkPolicy`) to be **byte-identical**, with a companion test that
the adapter half does differ — so the identity assertion cannot pass vacuously.

**The existing Azure deployment is untouched and stays that way.** `deploy/public/` deploys
Container Apps and keeps deploying Container Apps. PRD §22 forbids replacing it until the new
adapter demonstrates parity, and nothing in this ADR's PR touches it.

## Decision 2 — the contract is a document, and the application never reads it

`packaging/schema/acp-deployment.schema.json` defines `ACPDeployment`
(`packaging.acp.mova.io/v1alpha1`). The adapters consume it. **No application code reads it, and
no application code is changed by this ADR** — which is what keeps a packaging change from
becoming a runtime change.

Two layers, deliberately separate:

- **Structure** — the published JSON Schema. Readable by tooling that is not ours.
- **Semantics** — 19 rules in `packaging/cli/acpctl/spec.py` that a JSON Schema cannot express:
  profile floors, preset availability, the storage floor, the managed→embedded downgrade guard,
  the regulated posture, secret references, the egress allowlist, the connection budget.

Each rule names the PRD section it comes from and has a test that **makes it fire**. A rule with
no failing case is a claim, not a check.

**Errors fail; warnings do not.** A preview platform, an evaluation topology and a disabled AI
lane are legal choices, and a check that fails on a legitimate choice trains people to ignore it.

## Decision 3 — four things the contract refuses, and why each one

These are the rules worth reviewing, because each encodes a claim ACP would otherwise be able to
make without meeting it.

**Embedded data services in a production profile.** `standard`, `regulated` and
`high-availability` cannot set `mode: embedded` on Postgres, Redis or object storage. PRD §22:
do not silently downgrade from managed production services to embedded ones. The word "silently"
is the point — the downgrade is legal, it just cannot keep the profile name.

**A regulated profile that is not regulated.** External AI, cloud Langfuse, a provider telemetry
exporter, provider-managed keys, or under 30 days of backups each fail the `regulated` profile.
The profile name is what a compliance reviewer reads; it has to mean something.

**High availability without HA data services.** PRD §22: do not claim high availability without
failure testing. This contract cannot test failover, so it enforces the part it can see and the
claim stops being free.

**An autoscaling range the database cannot serve.** `api/store.py` sizes each replica's pool at
`ACP_WORKERS + _API_HEADROOM_CONN`, and every replica holds its own — so demand is set by *max*
replicas, not by load. A fleet comfortable at rest exhausts the server the first time it scales
out, which is the 2026-08-30 production incident (`psycopg2.pool.PoolError: connection pool
exhausted`, 16–64 times per revision across five revisions). The contract requires
`data.postgres.maxConnections` and rejects a document whose ceilings exceed it.

That last rule found something while it was being written. Applied to the PRD's own §9 example
replica ranges, a standard-production fleet needs **518** connections and a regulated one **604**
— against a production Postgres confirmed live at **150** `max_connections`. Nothing here says
the running fleet is over its limit; this repository cannot see the deployed `ACP_WORKERS` values
and no claim about production is being made. What it does say is that the PRD's illustrative
ranges are not deployable against the database ACP currently runs, and that the arithmetic
belongs in the contract rather than in a postmortem.

## Decision 4 — the storage floor sizes Assess and Remediate, and deliberately not Discover

Temporary worker storage is computed from max source size, concurrent files per worker, render
expansion, output and margin (PRD §12) — and applied only to the tiers that hold file bytes.

Discover is exempt because ADR 0020 made metadata-only discovery the default:
`api/handlers._defer_analysis_to_assess` opens no file and downloads nothing, and the download
plus analysis run at Assess time. Sizing the discovery tier for bytes it never holds would
inflate every plan.

**The exemption has a switch, and the contract does not yet model it.** That same function honours
`ACP_DEFER_ANALYSIS_TO_ASSESS=0`, which restores the legacy immediate-analysis scan that *does*
download at Discover time. An installation setting it invalidates the exemption. This is recorded
rather than solved: `_STORAGE_BEARING_TIERS` is the one line that must change when v1alpha2 models
the setting.

The expansion factors themselves (×4 render, ×1 output, ×1.5 margin) are **declared planning
constants, not measurements**. Nothing in this repository has measured peak per-worker scratch
against source size. `acpctl plan` labels them as such in its own output, and measuring them is a
named follow-up.

## Decision 5 — this release is read-only, and enforces that on itself

`acpctl` implements `validate`, `plan`, `inventory` and `values`. The other eight commands PRD §10
names exit 2 with the phase they belong to — accepting-and-ignoring is how an operator comes to
believe a backup ran.

Nothing in this release reaches a cloud, a registry, a cluster or a secret store, and
`tests/test_packaging_cli.py` asserts it by patching `open` to fail on any write mode. Two
consequences are stated in the plan output rather than papered over:

- **Image digests are `<unresolved>`.** A plan that printed a tag where a digest belongs is how a
  reviewer comes to believe a deployment is pinned when it is not (PRD §5.1).
- **Cost is `NOT AVAILABLE`.** No provider pricing source is wired up, and a fabricated range is
  worse than none because it gets quoted in a budget.

## Consequences

**Gained.** One reviewable description of an ACP installation, with the topology, the storage
model, the network posture and the connection budget derived from the running system rather than
restated. A `values` renderer that makes "one application package, four clouds" a testable
property. Four profiles whose names have enforced meaning.

**Costs and open items.**

- **Nothing is deployable from this yet.** No chart, no modules, no adapters. The contract is
  reviewable before implementation choices become expensive, which is PRD §23's whole intent, but
  it means `supported` currently applies to `compose` alone.
- **`azure` is `planned`, and that is a downgrade in wording only.** `deploy/public/` is a working
  ACA deployment; it is not the AKS adapter this contract describes, so the contract cannot claim
  it. Calling it `supported` here would be the "we wrote a module" support claim PRD §20.10 exists
  to prevent.
- **One duplicated constant.** `API_HEADROOM_CONN = 16` is copied from `api/store.py` because
  packaging must not import the application (the CLI ships in an air-gapped bundle without
  `api/`). `tests/test_packaging_inventory.py` pins the copy to the original.
- **`WORKER_THREADS_PER_CPU = 2`** is carried over from the reasoning in
  `deploy/compose/docker-compose.yml` (`ACP_WORKERS=8` on a 4-core host, I/O-bound on the vision
  call). It is a ratio, not a measurement of the deployed tiers, and it feeds the connection
  budget. Measuring real per-tier concurrency should replace it.
- **v1alpha1 gaps**, each a deliberate omission rather than an oversight: no GPU node selection,
  no multi-region, no per-image digest overrides, no air-gapped bundle manifest, and no model for
  `ACP_DEFER_ANALYSIS_TO_ASSESS`.

## What would reopen this

- A customer requiring a serverless container runtime (ACA/Cloud Run) as a first-class target,
  which would put Decision 1 back on the table with PDB/NetworkPolicy gaps to answer for.
- A measurement of per-worker scratch use that moves the storage floor materially.
- The Azure AKS adapter failing to reach parity with the Container Apps deployment, which would
  make "one Helm release" cost more than the divergence it prevents.

## Addendum — phase 2, the chart (2026-09-04)

The chart this ADR specified now exists at `packaging/chart/acp`, and building it settled three
things the contract left open. Recorded here rather than in a new ADR because none of them changes
a decision above; they are what those decisions turned out to mean in practice.

**The chart does not vendor data-service subcharts, and a document asking for in-cluster data
services fails the render.** `acpctl values` emits `chart: bitnami/postgresql`,
`bitnami/redis` and `minio` for `self-hosted` and `embedded` modes. Vendoring those would make
the ACP application package depend on three third-party charts whose registries, cadence and
licensing ACP does not control — Bitnami's own chart README now points readers at a separate
"Bitnami Legacy" registry for the previous image generation, which is the kind of change that
breaks an install months after review. It would also blur the boundary this ADR is built on: a
chart that ships its own Postgres has quietly answered the question the adapter exists to answer.

So the chart consumes an *endpoint*, and `helm template` fails with a message naming the mode
when asked for anything else. The alternative — render the application and note the gap — installs
an ACP that cannot start and reports success doing it. **The practical consequence is that the
`regulated` example as shipped does not render without an override** (`--set
postgresql.external=true`, etc.), because that profile asks for `self-hosted`. That is a real
limitation and the escape path is tested; whether `self-hosted` should mean "in-cluster, and the
operator provisions it" rather than "in-cluster, and the chart provisions it" is a contract
question worth deciding deliberately, and this addendum does not decide it.

**The worker autoscaler had to learn what the queue actually looks like.** The natural KEDA
trigger from reading the values file is `WHERE role = '<role>'`. The `jobs` table has no `role`
column — it has `type`, and a role maps to a *tuple of job types* in `api/core.py`. A scaler
against a missing column is a Postgres error that KEDA logs while scaling nothing: the tier sits
at its floor, the backlog grows, and the only symptom is autoscaling that never happens. The lane
lists are now emitted by `acpctl` from `inventory.LANE_JOB_TYPES`, which
`tests/test_packaging_chart.py` pins against `core`'s own tuples and against the handler registry.

**The portability claim is now checked on rendered objects, not just on values.**
`test_packaging_values.py` establishes that the application half of the *values* is identical
across platforms — a claim about the renderer. `test_packaging_chart.py` renders four platforms
through `helm template` and requires the Deployments and Jobs to match, with the adapter-owned
fields (image registry, platform label, `ACP_PLATFORM`) normalised away and a companion test
asserting the adapter half genuinely differs. A template *can* special-case a cloud
(`if eq .Values.acpDeployment.platform "azure"`) and no values test would notice; this one does.
`ACP_PLATFORM` is normalised only because nothing reads it, which is itself asserted — the moment
application code branches on it, the normalisation would be hiding the fork it exists to catch.

Three cluster prerequisites are rendered-but-unenforceable, and two of them fail **silently**:
a `ScaledObject` without KEDA and a `NetworkPolicy` under a CNI that does not implement them are
both accepted by the API server and quietly do nothing. `acpctl doctor` is where those become
checkable preconditions, and it is not built.
