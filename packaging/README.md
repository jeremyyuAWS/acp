# ACP packaging

One application package, deployed consistently to Kubernetes — on AKS, EKS, GKE or a customer's
own cluster — with Docker Compose as the evaluation option. See
[ADR 0048](../docs/adr/0048-portable-deployment-packaging.md) for the architecture and the
decisions behind it, and [`docs/service-inventory.md`](docs/service-inventory.md) for what an
installation actually consists of at each profile.

**Still read-only.** `acpctl` provisions nothing and contacts no cluster, and nothing here touches
the existing Azure Container Apps deployment in `deploy/public/` or the Compose stack in
`deploy/compose/` — those keep working exactly as they do today and are not retired until a
replacement demonstrates parity. What phase 2 adds is the **chart** the values were always being
rendered for: `helm template` produces real manifests, and `helm install` is a decision an
operator makes, not something a tool here does for them.

## Layout

```
packaging/
  schema/acp-deployment.schema.json   the published contract
  cli/acpctl/                         validate · plan · inventory · values
  chart/acp/                          the Helm chart the values install
  examples/                           one document per deployment profile
  docs/service-inventory.md           GENERATED — scripts/gen_service_inventory.py
```

## The chart

```bash
python -m acpctl values packaging/examples/standard-production.acp-deployment.yaml > values.yaml
helm template acp packaging/chart/acp -f values.yaml
```

It installs the **application**: the API tier, the three worker tiers, their autoscalers, the
network policy, the secret wiring, and the migration and preflight hook jobs.

It does **not** install Postgres, Redis or object storage, and a document asking for in-cluster
data services (`mode: self-hosted` or `mode: embedded`) **fails the render** rather than
proceeding. That is deliberate: the application package is what is identical across platforms and
data services are what the adapter supplies, so rendering the app against a database nobody
created would install a workload that cannot start and report success doing it.

An operator who provisions those services by other means — their own Postgres operator,
CloudNativePG, a managed instance — sets `external: true` and supplies the endpoint through
`secrets.refs`. That is the supported path:

```bash
helm template acp packaging/chart/acp -f values.yaml \
  --set postgresql.external=true --set redis.external=true --set objectStorage.external=true
```

### What the cluster must already have

The chart renders these objects whether or not the cluster can act on them, and in two of the
three cases **Kubernetes reports nothing when it cannot**:

| Rendered | Needs | If absent |
|---|---|---|
| `ScaledObject` | KEDA | no error; workers stay at their floor and the queue grows |
| `NetworkPolicy` | a CNI that enforces them | no error; pod networking stays open |
| `ExternalSecret` | External Secrets Operator | pods stay in `CreateContainerConfigError` |

Only the third is loud. `acpctl doctor` is where these become a checkable precondition, and it is
not built yet — until then they are in the chart's NOTES and here.

## Using it

```bash
export PYTHONPATH=packaging/cli

python -m acpctl validate  packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl plan      packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl inventory packaging/examples/regulated.acp-deployment.yaml --json
python -m acpctl values    packaging/examples/regulated.acp-deployment.yaml
```

`validate` exits 0 on success and 1 on any error; warnings are printed and never fail. The other
eight commands from the PRD's command list exit 2 and name the phase they belong to, rather than
accepting arguments and doing nothing.

## The four profiles

| Profile | Platform | Data services | Notable requirements |
|---|---|---|---|
| `evaluation` | `compose` only | embedded | single machine, no HA |
| `standard` | any Kubernetes | managed or self-hosted | ≥2 API replicas, ≥7-day backups |
| `regulated` | any Kubernetes | managed or self-hosted | local-only AI, local telemetry, customer-managed keys, ≥30-day backups |
| `high-availability` | any Kubernetes | HA required | ≥2 replicas per critical tier, PDBs |

A profile's name is enforced, not decorative: `regulated` with external AI, or
`high-availability` without HA Postgres, is a validation error.

## Changing the chart

`tests/test_packaging_chart.py` renders it through `helm template` and asserts on the manifests,
not on the template source — the interesting properties (what the object contains, whether
`replicas` is present, whether two clouds produce the same Deployment) are properties of the
render. It needs helm on PATH; CI installs it with `scripts/install_helm.sh`, and
`test_ci_has_helm` fails rather than skips when CI has none, so the whole file cannot quietly
stop running.

## Adding a rule

Semantic rules live in `cli/acpctl/spec.py` and policy tables in `cli/acpctl/presets.py`. Every
rule needs a test in `tests/test_packaging_validate.py` that **makes it fire** — take a valid
example, break exactly one thing, assert the rule id. A rule with no failing case is a claim, not
a check.

Changing the contract or an example means regenerating the inventory:

```bash
python scripts/gen_service_inventory.py           # rewrite
python scripts/gen_service_inventory.py --check   # what CI runs
```
