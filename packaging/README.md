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
  schema/acp-release.schema.json      what one release consists of, and how to pin it
  cli/acpctl/                         validate · plan · inventory · values · release
  chart/acp/                          the Helm chart the values install
  examples/                           one document per deployment profile, plus one release
  reference/kind/                     the disposable cluster CI installs on — see below
  docs/application-configuration.md   which variables reach the app, and how to set the rest
  docs/service-inventory.md           GENERATED — scripts/gen_service_inventory.py
  docs/kubernetes-mvp-gap-report.md   what the cluster establishes, and what still blocks a
                                      real release
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

Only the third is loud. **`acpctl doctor` is where these become checkable** — run it against
the target cluster before installing (see below).

### The chart is installed on a real cluster, not only rendered

`packaging/reference/kind/` and `.github/workflows/packaging-kind.yml` install this chart on a
throwaway `kind` cluster on every packaging pull request: the image is built from the checkout and
`kind load`ed with no registry, Postgres and Redis are supplied the way an infrastructure adapter
would, and then the running installation is asked the questions `acpctl` was written to ask.

**A rendered manifest and an accepted one are different claims, and the gap is not theoretical.**
Three defects were found BY THE INSTALL, each one green under every rendered-manifest test:

| Found by the cluster | Why no render could |
|---|---|
| no `helm install` had ever succeeded | Helm runs pre-install hooks before the release's own ServiceAccount exists, so the Job produced no pod at all. Both objects render perfectly; only the install has an ordering. |
| a numeric annotation was rejected by the API server | `toYaml` preserves YAML's types and annotations are `map[string]string`. A test that parses the render gets the value back as an int and asserts on it happily — the defect is in the type, which is what a round-trip through a parser erases. |
| `helm install` failed wherever NetworkPolicy is enforced | the chart's own egress policy blocked its own preflight hook. Every policy renders correctly; whether anything acts on them is a property of the CNI. |

A further three were found by reading the application against the chart rather than the chart
against itself — worker Deployments that inherited the image's CMD and ran the API server, a
readiness probe pointing at a route that never sets a status code, and a default-deny policy with
no DNS egress. Those did not need a cluster, only a habit: `docs/application-configuration.md` and
`tests/test_packaging_seams.py` are what that habit turned into.

The cluster runs Calico rather than kind's kindnet, because kindnet accepts NetworkPolicy objects
and enforces none of them — the "no error; pod networking stays open" row of the prerequisites
table above. A cluster that cannot enforce a policy cannot test one. It also enforces the
restricted Pod Security Standard, so a pod that does not meet it is rejected at
admission rather than merely looking compliant. And it upgrades the release as well as installing
it, because an install that cannot be upgraded is a demo.

**What it does not establish** is recorded in `docs/kubernetes-mvp-gap-report.md` in the same
detail: one node, a Kubernetes version this chart RUNS on rather than one anything is supported
on, and no document ever scanned or remediated on it.

## Using it

```bash
export PYTHONPATH=packaging/cli

python -m acpctl init      --profile standard --platform azure --name acp-prod
python -m acpctl validate  packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl plan      packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl inventory packaging/examples/regulated.acp-deployment.yaml --json
python -m acpctl values    packaging/examples/regulated.acp-deployment.yaml
python -m acpctl doctor    packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl status    packaging/examples/standard-production.acp-deployment.yaml
```

`validate` exits 0 on success and 1 on any error; warnings are printed and never fail. The
remaining commands from the PRD's command list exit 2 and name the phase they belong to, rather
than accepting arguments and doing nothing.

## `init` — start from something valid

```bash
python -m acpctl init --profile regulated --platform azure --name acp-prod \
  --region eastus2 --registry acr.example.org/acp -o acp.yaml
```

Writes to **stdout** unless you pass `-o`, so `acpctl init > acp.yaml` is the ordinary use and the
read-only guarantee holds by default. With `-o` it **refuses to overwrite** an existing file —
that file is the record of a deployment and may describe something already installed. There is
deliberately no `--force`.

### Why this is more than a template

The contract has 37 semantic rules on top of its schema, and they interact: `regulated` needs
local-only AI *and* local telemetry *and* customer-managed keys *and* ≥30-day retention;
`evaluation` is Compose-only, and Compose has no managed data services; which secret providers are
legal depends on the platform; which secret refs are *required* depends on which data services are
external and which connectors are on. Starting from a copied example means meeting those rules one
validation error at a time.

So the defaults are **derived from the same policy tables the validator enforces** —
`presets.PLATFORM_DATA_MODES`, `PLATFORM_SECRET_PROVIDERS`, `PROFILE_MIN_REPLICAS` — and the
required secret refs come from `spec.required_secret_names`, the function `validate` itself uses.
A generator with its own idea of what `regulated` means would drift from the validator, and the
result would be a document that init produced and validate rejects.

**Every document `init` emits passes `validate`, for every legal (profile, platform) pair**, and
`tests/test_packaging_init.py` checks all sixteen. That is not a formality: the first draft failed
12 of the 16 twice over — once for invented telemetry exporter names, once for evaluation replica
ceilings that needed 372 Postgres connections against a server declared at 100. Both were found by
running the real validator over the real output.

The generated file is **commented**, because it is the one an operator reads and keeps. It is also
valid-but-not-finished: `runtime.publicUrl`, `runtime.imageRegistry` and every entry under
`secrets.refs` are placeholders, and the file says so at the top.

## `doctor` — can this cluster run it?

The only command that leaves the machine. It reads a live cluster through `kubectl`, so it
inherits your kubeconfig, context and credentials, and it **changes nothing**: an allow-list
refuses any kubectl verb that is not `version`, `api-resources` or `get`, and that refusal is
tested against a dozen mutating verbs. Phase 0 kept the read-only promise by patching `open` in a
test, which cannot see a subprocess — this is the replacement, not an addition to it.

```bash
python -m acpctl doctor packaging/examples/standard-production.acp-deployment.yaml -n acp-prod
python -m acpctl doctor <spec> --context staging --json
```

| Exit | Meaning |
|---|---|
| 0 | no blockers (warnings may still be printed, and are worth reading) |
| 1 | a blocker, **or** a blocking check that could not be run |
| 2 | the cluster could not be reached, so nothing was established — retryable |

### It exists for two silent failures

Most misconfigurations announce themselves. These two do not, and the chart renders both:

- **A `ScaledObject` with no KEDA** is an object nothing reconciles. No error, no event, no
  status. The worker tiers sit at their floor while the queue grows, and it looks like ACP being
  slow.
- **A `NetworkPolicy` under a CNI that does not implement them** is accepted by the API server and
  enforces nothing. A regulated install can pass review with completely open pod networking.

Everything else `doctor` checks is ordinary preflight. Those two are why there is a command.

### Three outcomes, not two

`pass`, `fail`, and **`unknown`** — and the third is what keeps the report honest. A check that
could not run has established nothing, so folding it into "pass" because nothing went wrong is how
a report comes to mean the opposite of what it says. An `unknown` on a check guarding a silent
failure counts as a blocker.

`doctor` cannot prove NetworkPolicy enforcement — no API reports it — so it infers from the CNI
and says so in the finding rather than implying certainty. It does not connect to Postgres, Redis
or object storage either; that would mean shipping credentials to a laptop. The connection-budget
rule in `spec.py` is the static half of that question.

## `status` — is what is running still what the document says?

`doctor` asks whether a cluster *can* run the document, before an install. `status` asks whether
what is running *is* the document, after one. Same read-only guarantee: it reuses the same kubectl
allow-list, and the end-to-end test asserts on the log that every call it made was a read.

```bash
python -m acpctl status <spec> -n acp-production
python -m acpctl status <spec> --context prod --json
```

| Exit | Meaning |
|---|---|
| 0 | installed, healthy, and matching the document |
| 1 | degraded, drifted, nothing installed here, or a blocking check that could not run |
| 2 | the cluster could not be reached — retryable, and deliberately not 1 |

### The drift half is the part nothing else does

`kubectl get pods` shows health. What no other tool checks is whether the deployment document
still describes the installation — and `acpctl values` stamps this on every file it renders:

> edit the deployment document and regenerate, or the two disagree and the document stops being
> the record of what was installed

A `kubectl scale`, a hand-edited values file, a half-finished upgrade: each leaves the document
describing something that no longer exists, silently, and the document is what the next operator
reads before making a change.

### Autoscaling is not drift

The obvious check compares running replicas against the document's `replicaCount` — and fires on
**every healthy autoscaled tier**, because `replicaCount` is the floor and a KEDA tier configured
3–10 and sitting at 7 is the system working. A report that is red on every correct installation is
one nobody reads, and then the real drift is unread with it.

So an autoscaled tier is judged on whether its count is inside its range; a tier with no
autoscaler is judged on the exact number, since nothing legitimately changes it. Those are
opposite rules and they are separate branches, not one comparison with a tolerance.

Two more comparisons that look obvious and are wrong:

- **The release is compared on the `app.kubernetes.io/version` label, not the image string.**
  `acpctl install` pins digests, so a correctly-installed release runs `repo@sha256:…` while the
  document names a tag — comparing image strings would call every properly-pinned install drifted.
- **The document is checked against the installation before anything else.** Pass the wrong
  environment's file and every comparison below is against the wrong baseline; the output would be
  a list of confident falsehoods that sends somebody to "fix" a healthy installation. Profile and
  platform are on the labels, so that case is detectable — and when it fires, the comparison
  stops rather than continuing in colour. Health is still reported, because health does not depend
  on the document at all.

## `release verify` — is this a release something can be installed from?

A deployment document says what an installation should be. A **release manifest** says what one
ACP release consists of: one entry per built artifact, with its digest, the commit it was built
from, its architectures, its SBOM and its signature.

```bash
python -m acpctl release verify packaging/examples/example.acp-release.yaml
python -m acpctl values <spec> --release <manifest>   # image.digests, pinned
python -m acpctl plan   <spec> --release <manifest>   # digests instead of <unresolved>
```

The shipped example is published under a registry in a reserved TLD that can never resolve, so a
copy of it fails at pull time rather than installing digests nobody chose — and `release verify`
says so as the `release.illustrative` warning.

### It reconciles three counts that disagreed

PRD §5.1 names **eight** images. The chart pulls **four**. `deploy/public/deploy.sh` builds **one**
application image that serves the API and all three worker roles, plus Grafana and the model image.
All three are correct about different things, and before this contract they disagreed silently:
`acpctl plan` named `acp-web-api` and `acp-discovery-worker` while `helm template` deployed `acp`
and `acp-worker`, and nothing built any of those four. Two names out of eight overlapped.

So a component here is an **artifact that was actually built**, and it declares what it provides:

```yaml
- name: app
  repository: acp-app
  digest: "sha256:…"
  serves: [api, discover, assess, remediate, migrations, preflight]   # PRD S5.1 images
  chartImages: [api, worker]                                          # what the chart pulls
```

Two rules make the old state un-representable. Every image `acpctl plan` names must be served by
exactly one artifact — otherwise a reviewer signs off a list of things nobody built. Every image
the chart pulls must be backed by exactly one artifact — and that one matters more, because it
fails **silently**: `acp.image` falls back to the tag when `image.digests` has no entry, so the
install succeeds and is simply not pinned.

### What it does not do

It reaches no registry. So it cannot prove a digest exists, cannot verify a signature, and cannot
confirm an SBOM is at the URI it names. What it establishes is that the release **declares** those
things and that the declarations are consistent — one source revision across every artifact
(PRD §5.1), a signature and an SBOM per artifact, amd64 everywhere, and arm64 recorded per image
rather than claimed for the release. Verifying a signature needs the registry and the trust root
and is `acpctl install`'s job; leaving that gap explicit is the point.

`--release` never degrades. A caller who passes a broken manifest gets exit 1 and no output, not
an unpinned values file that reads exactly like a pinned one.

## What an installation keeps, and the one field that decides it

`data.objectStorage.account` names the storage account holding remediated output. **Omit it and
the installation keeps nothing.**

`api/blob.py` is the primary store for a remediated file's fixed copy (ADR 0010) and decides
whether it exists from `ACP_BLOB_ACCOUNT` alone. Unset, every function returns `None` — so ACP
remediates a document, logs that the corrected copy was stored, and records the digest and the
byte count while dropping the bytes. There is no database column for them (ADR 0010 rejected one)
and no filesystem fallback.

The chart set that variable for the first time on 2026-09-08. `deploy/public/deploy.sh` had always
set it, so Container Apps persisted output and every Helm install silently did not.
`acpctl validate` now warns when a document omits the account, and the warning names the
consequence rather than the missing field.

**The only implementation is Azure Blob.** `api/blob.py` builds
`https://<account>.blob.core.windows.net` and authenticates with `DefaultAzureCredential` — no
endpoint override, no key-based path, no S3 client anywhere in `api/`. PRD §7 maps object storage
to S3 and Cloud Storage on the other platforms and nothing implements them, so a non-Azure
installation naming an account is asking that cluster to reach Azure, and gets a second warning
saying so. Making that portable is an application change, not a packaging one.

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
