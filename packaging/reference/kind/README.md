# The disposable reference cluster

A throwaway Kubernetes cluster that **installs** the ACP chart, rather than rendering it. Created
per CI run, deleted at the end of it, and pinned to one Kubernetes version so the result names
something.

```
acp-deployment.yaml     the document it installs — a real one, `acpctl validate` accepts it
cluster.yaml            one kind node, Kubernetes pinned by tag
data-services.yaml      Postgres and Redis: the endpoints the chart deliberately does not own
runner-resources.yaml   the one departure from the document, and why
```

Driven by `.github/workflows/packaging-kind.yml`; guarded offline by
`tests/test_packaging_reference_kind.py`.

## Why an install and not more render tests

`tests/test_packaging_chart.py` renders the chart and asserts on the manifests, which is the right
way to check what a template produces. It also compares the chart **against itself**, so a chart
that renders the wrong thing consistently passes.

Two defects found on 2026-09-08 were both green under tests that named them:

- **Worker Deployments ran the API.** No `command`, so the container inherited the image's CMD,
  which starts uvicorn. The pods reported Ready and claimed no jobs.
- **The API readiness probe could not fail.** It pointed at a route that never sets a status code.

Neither was reachable by rendering. Both would have died at the first `helm install` — the worker
one at the assertion below, the probe one the first time a replica came up before its database
did. That is what this cluster is for.

## What it establishes

- The manifests are **accepted by a real API server**, not merely well-formed.
- Migrations run, the API tier starts, and it reaches Postgres and Redis.
- **Every worker tier registers and heartbeats.** `/readyz` reports
  `workers.roles.<role>.alive` per role, unauthenticated. A worker Deployment running the API
  rolls out perfectly and never writes a heartbeat, so `kubectl rollout status` passes and this
  assertion does not — which is precisely the defect it was written for.
- `acpctl status` finds the installation and agrees it matches the document.

## What it cannot establish, and must not be read as

| Not tested | Why |
|---|---|
| NetworkPolicy enforcement | kind's default CNI accepts policies and enforces nothing. `acpctl doctor` reports that as a blocker, and is right to — the job records the finding and does not fail on it. |
| Zone spreading, disruption budgets | One node. A spread constraint satisfied on one host says nothing about zones. |
| Managed data services | Postgres and Redis are plain Deployments on `emptyDir`. Running a container is not evidence about a managed service's failover or backup behaviour. |
| Capacity or performance | `runner-resources.yaml` lowers requests to fit a 4-CPU runner. |
| Anything about a **release** | The image is built from the checkout and loaded by tag. It carries no digest, no signature and no SBOM, so a green run is evidence about a commit, not about a release (PRD §5.1). |

A pass here is **not** a support claim. Support needs the full acceptance suite, an upgrade from
the previous release, a real restore, and recovery testing. `kubernetes` stays `planned` in
`presets.SUPPORT_STATUS` until those exist.

## Running it yourself

Needs docker, and about fifteen minutes for the image on a cold cache.

```bash
dotnet build spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj -c Release   # bin/ is gitignored
docker build -f deploy/public/Dockerfile -t acp-app:ci .
bash scripts/install_helm.sh && bash scripts/install_kind.sh
kind create cluster --config packaging/reference/kind/cluster.yaml
kind load docker-image acp-app:ci --name acp-reference
```

Then follow the workflow's remaining steps — it is the executable version of this paragraph, and
the tests above assert the two do not disagree about the namespace, the secret keys, the service
names or the Postgres connection ceiling.

**No registry is involved anywhere.** `kind load` copies the local image into the node's
containerd and `image.pullPolicy: Never` makes Kubernetes use it. An install that reached a
registry would be testing the registry as much as the chart, and would need credentials this job
deliberately does not have.

## The one departure from the document

`runner-resources.yaml` lowers **requests only**. The document asks for 1 CPU and 4Gi of temporary
storage per pod; five pods of that is 5 CPU and 20Gi requested, against a runner with 4 CPU and
about 14GB of disk. Limits stay exactly as the document sets them, so a worker still cannot exceed
its preset's temporary storage. `test_the_runner_overrides_touch_nothing_but_requests` keeps that
file from growing into a second deployment document.
