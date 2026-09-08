# Kubernetes MVP: what exists, what is missing, what blocks the next step

## What this is

The Kubernetes MVP is the milestone at which one ACP release can be installed onto a throwaway
cluster by `acpctl`, exercised by an automated acceptance suite, and upgraded, rolled back and
restored — with every artifact it runs identified by an immutable digest. This report maps the
repository against the four workstreams the implementation PRD defines (A release artifacts,
B Helm hardening, C acceptance suite, D `acpctl` lifecycle) and says, for each, what is *blocking*
rather than what is merely absent.

Every claim below names the file and line, or the command and its output and exit code, that
produced it. Where something could not be run it says so, and the finding is marked unverified
rather than asserted.

**No target moves from `planned` to `supported` here, and none can.**
`presets.SUPPORT_STATUS` (`packaging/cli/acpctl/presets.py:68-75`) marks `compose` supported and
every Kubernetes target `planned`, and its own definition of the word is *"a reference deployment
in THIS repository runs the contract suite against it"*. PRD §7 requires the packages to document
which combinations are production-supported versus preview, and §9/§20.3 make a support claim mean
the reference deployment passed the smoke suite. A rendered chart and a green unit suite are
evidence that a template produces the text it was written to produce; they are not evidence that
anything runs. Nothing in this repository has acceptance evidence, so nothing in this report is
`verified`.

**What a first acceptance run would need.** None of it exists here, and standing it up is the
owner's decision rather than a step in this change — `packaging/` provisions nothing by design
(`packaging/README.md:18-21`), and this is a billable environment with real blast radius.

| Needed | Why the run cannot substitute for it |
|---|---|
| A disposable Kubernetes cluster with admin | KEDA, an ingress controller, a NetworkPolicy-enforcing CNI and PodSecurity admission are all cluster-level, and three of them fail silently (prerequisites table below). kind/k3d covers render and admission, not zone spreading or a real LoadBalancer |
| External Postgres, Redis and S3-compatible object storage | The chart refuses to render against in-cluster data services (verified below); `standard-production` needs `max_connections >= 418` (`packaging/docs/service-inventory.md`) |
| A registry the cluster can pull from, holding images built from this repo | Nothing in this repository builds the artifacts a release manifest would name — gap A2 |
| A throwaway DNS name and TLS secret, or an ingress controller with a default class | The rendered Ingress names no class and a TLS secret nothing creates |

---

## Closed since this report was opened

Three findings this report carried are now fixed on `main`. They are named rather than deleted,
because how they were found is the transferable part.

| Was | Closed by | How it was found |
|---|---|---|
| Worker Deployments set no `command`, so they inherited the application image's uvicorn CMD and ran the API: Ready, bound, claiming no jobs | `0f92cd7` (#1798) — `workerCommand` (`values.yaml:66`), rendered at `worker-deployment.yaml:78` | By reading the application against the chart. `test_workers_get_no_http_probes` was green throughout: the chart *does* declare no probes, while the container it rendered was an HTTP server |
| API readiness probed `/readyz`, whose handler never sets a status, so the gate could never close | `0f92cd7` (#1798) — `_helpers.tpl:214` now probes `/probe/readyz`, liveness stays `/healthz` (`:222`) | Same way. The old test pinned the path the chart had, not a path that can return 503; the new one asserts the probed path is a route in `api/routes/system.py` that takes a `Response` and sets 503 |
| The plan named eight images, the chart pulled four under different names, and nothing built any of them | `1a8b510` (#1797) — `ACPRelease`, `acpctl release verify`, `--release` on `values`/`plan` | By diffing `acpctl plan` against `helm template` output. Section A says precisely how much of this is closed and how much is declared-but-unproduced |

**The lesson, because it generalises.** A rendered-manifest test compares the chart against itself,
so a chart that renders the wrong thing consistently passes. Neither #1798 defect was reachable
without reading the application the chart deploys, and neither would have survived one `helm
install` on a real cluster. That is the argument for the blocking gap in section B, made from the
inside.

---

## How the chart findings were produced

`helm` is available here, so every chart claim below is an observation of rendered output rather
than a reading of template text. `kubectl` is **not** installed and no cluster is reachable, so
nothing cluster-side is claimed.

```
$ helm version --short
v3.16.3+gcfd0749                                                        exit=0
$ command -v kubectl                                                    exit=1
$ export PYTHONPATH=packaging/cli
$ python -m acpctl values packaging/examples/<profile>.acp-deployment.yaml > values.yaml
$ helm template acp packaging/chart/acp -f values.yaml
```

| Example | `helm template` | Note |
|---|---|---|
| `standard-production` | exit 0, 22 objects | platform `azure`, ESO path |
| `high-availability` | exit 0, 24 objects | adds a PDB and a third `ScaledObject` |
| `regulated` | **exit 1** | `postgresql/redis/objectStorage (mode: self-hosted)` refused; renders with the documented `--set …external=true` escape |
| `evaluation` | **exit 1** | `mode: embedded`; Compose-only by contract, so this is correct behaviour, not a defect |
| `acpctl init --platform kubernetes --profile standard` | exit 0, 22 objects | the customer-cluster MVP path; **renders no Secret and no ExternalSecret** |

```
$ python -m acpctl doctor packaging/examples/standard-production.acp-deployment.yaml -n acp
  [????] cluster.reachable: kubectl is not on PATH. …
         -> Nothing below could be checked. This is not a pass.
NOTHING WAS CHECKED — the cluster could not be reached. This is not a pass.
                                                                        exit=2
$ python -m pytest tests/test_packaging_chart.py -q
46 passed, 1 skipped                                                    exit=0
```

Not checkable here, and not claimed anywhere below: admission behaviour, KEDA/ESO reconciliation,
NetworkPolicy enforcement, image pulls, scheduling, and anything `doctor`/`status` reads.

---

## What the chart RENDERS versus what the cluster must already provide

`packaging/README.md:64-72` carries three rows. All three are still true; the chart renders more
than they admit. **Silent** means Kubernetes accepts the object and nothing reports that it does
nothing.

| Rendered object | Cluster must provide | If absent | Loud? | Checked by `doctor`? |
|---|---|---|---|---|
| `ScaledObject` ×2–3, `TriggerAuthentication` | KEDA (CRDs **and** a running controller) | CRDs missing: apply fails. CRDs present, controller not: workers sit at their floor and the queue grows | mixed | yes (`doctor.py:191`) |
| `NetworkPolicy` ×4 (`default-deny`, `api`, `worker-no-ingress`, `egress`) | a CNI that enforces them | pod networking stays fully open | **no** | inferred only (`doctor.py:217`) |
| `ExternalSecret` (ESO backends only, `secret.yaml:23-24`) | External Secrets Operator + a `SecretStore` | pods stay in `CreateContainerConfigError` | yes | yes (`doctor.py:256`) |
| **nothing** — when `secrets.provider: kubernetes` | a pre-created Secret `<release>-secrets` carrying every `secrets.refs` key | same `CreateContainerConfigError` | yes | **no** — `check_external_secrets` returns `[]` when ESO is off (`doctor.py:257-259`) |
| `HorizontalPodAutoscaler` with a `Resource: cpu` metric | metrics-server | `FailedGetResourceMetric`, no API scaling | quiet | yes (`doctor.py:339`) |
| …and a `Pods: acp_concurrent_requests` metric | a custom-metrics adapter **and an application that exports it** | `FailedGetPodsMetric`; see C2 | quiet | partially |
| `Ingress`, no `ingressClassName`, `secretName: acp-tls` | a **default** IngressClass, and something that creates `acp-tls` | no class default: never reconciled. no secret: controller serves its own cert | **no** | class existence only (`doctor.py:317`) |
| every workload image | a registry holding the four repositories the values name, pullable without a pull secret (`imagePullSecrets`: 0 hits in the render, exit 1, against a control of 8 `serviceAccountName` hits) | `ImagePullBackOff` | yes | no |
| every pod, no `seccompProfile` | a namespace **not** enforcing PodSecurity `restricted` | pods rejected at admission | yes | no |
| `ai.ollama.gpu: true` | nothing — see B9 | the model runtime schedules onto a CPU node and no object says otherwise | **no** | no |

Row 1's qualification matters and the README's version does not carry it: "no error" holds only
when the KEDA **CRDs** are installed and the controller is not. *Unverified — no cluster; reasoned
from the API-server contract.*

Row 4 is the customer-Kubernetes default. `acpctl init --platform kubernetes` writes
`secrets.provider: kubernetes` (line 141 of its output), `secret.yaml` renders an `ExternalSecret`
only for ESO backends, and the resulting 22-object manifest set contains **no `Secret` of any
kind** — verified by rendering it (`grep -n "^kind: Secret"` → exit 1). So the first prerequisite
an MVP-path operator hits is the one `doctor` does not ask about.

---

## A. Release artifacts and supply chain

**What exists.** `packaging/cli/acpctl/inventory.py:61-75` names PRD §5.1's eight logical images.
`1a8b510` (#1797) added the release manifest that reconciles them with what is built and what the
chart pulls: `ACPRelease` (`packaging/schema/acp-release.schema.json`), its rules
(`packaging/cli/acpctl/release.py`), `acpctl release verify`, and `--release` on `values` and
`plan`. A component in a manifest is one **built artifact**, declaring which logical images it
`serves` and which chart image components it `chartImages`-backs; two rules make the old
divergence unrepresentable — `_rule_serves_every_logical_image` and `_rule_backs_every_chart_image`
(`release.py`). The second is the one that matters, because `acp.image` (`_helpers.tpl:56-81`)
falls back to the tag when `image.digests` has no entry, so an unbacked component installs
successfully and is simply not pinned.

**How much of the naming disagreement this closes: all of it, but only when a manifest is passed.**

```
$ python -m acpctl values <doc> --release packaging/examples/example.acp-release.yaml \
    | helm template acp packaging/chart/acp -f -                        exit=0
```

renders **seven** image references, every one by digest, against three artifacts
(`acp-app`, `acp-ollama-gateway`, `acp-grafana`) — the API, three workers, the migration and
preflight Jobs all resolve to `acp-app@sha256:347d6d…`. Without `--release`, `values.py:233-241`
leaves `repository`/`workerRepository` **absent** deliberately, the chart defaults apply
(`values.yaml:23,25` — `acp` and `acp-worker`, names nothing builds), `digests` is `{}`
(`values.py:161`), and the file is stamped *"Image digests are UNRESOLVED here"*
(`values.py:308-309`). So the default `acpctl values` path is exactly as unpinned as before; the
pinned path is opt-in and requires a manifest that does not yet exist.

Two residues survive the reconciliation and are worth knowing before an install:

- `acp-migrations` and `acp-preflight` still have no chart component. `migration-job.yaml:53` and
  `preflight-job.yaml:44` both render `include "acp.image" (dict "root" $ "component" "api")`, so
  the hooks run the API image. The manifest models this honestly — one artifact `serves` all six —
  but the plan still presents two artifacts that no separate image backs.
- The Ollama artifact the manifest and chart name (`acp-ollama-gateway`, from
  `deploy/ollama/Dockerfile`) is built by nothing. `deploy/ollama/gpu-runbook.sh:45` builds
  `acp-ollama` from `Dockerfile.gpu` — a different image under a different name.

**A2 — the rest of PRD §5.1 is declared, not produced, and the distinction is the whole point.**
`release verify` establishes that a release *declares* these things and that the declarations are
internally consistent; `release.py`'s own module docstring states that it contacts no registry, so
it cannot prove a digest exists, cannot verify a signature, and cannot confirm an SBOM is at the
URI it names.

| PRD §5.1 property | Expressible in `ACPRelease`? | Refused by `release verify`? | Produced by anything in this repo? |
|---|---|---|---|
| One source revision across the release | yes (`metadata.sourceRevision`) | yes — `release.mixed-revision`, an error | no build emits a manifest |
| Immutable digest per artifact | yes (`digest`, schema-required) | yes, structurally | no |
| SBOM per image | yes (`sbom`) | yes — `release.no-sbom` | **no** — `syft`/SPDX/CycloneDX: 0 files under `.github/`, `azure-pipelines.yml`, `scripts/`, `deploy/` |
| Cryptographic signature | yes (`signature`) | yes — `release.unsigned` | **no** — `cosign`/`sigstore`/`in-toto`: 0 files, same search |
| Signature **verified before install** | no | no — out of scope by design | no; it needs the trust root and is `install`'s job (§D) |
| Vulnerability scanning gate | **no** — the component schema has no scan or vulnerability field at all (`architectures, chartImages, digest, name, repository, sbom, serves, signature, sourceRevision, tag`) | n/a | **no** — `grype`/`trivy`: 0 files |
| Build provenance / SLSA attestation | **no** — `$defs/attestation` is used for `sbom` only | n/a | no |
| arm64 recorded **per image** | yes (`architectures`) | warning — `release.partial-arm64` | no; and per *analysis engine*, which §5.1 asks for, is not expressible: components are artifacts and engines are not modelled |

The shipped example is deliberately unusable as a real manifest — `registry.invalid`,
`sourceRevision: 0000…`, `amd64` only — and `release verify` says so rather than letting a copy of
it install fabricated digests:

```
$ python -m acpctl release verify packaging/examples/example.acp-release.yaml
Warnings (1):
  metadata.registry: 'registry.invalid/acp' is in a reserved TLD that cannot resolve …
  … 3 artifact(s) …
  Signatures and SBOMs are DECLARED, not verified — verifying them needs the
  registry, and is `acpctl install`'s job.                               exit=0
```

**The blocking gap: nothing builds, signs, SBOMs or scans an artifact, so CI has no release to
fail on.** What is built today is `acp-app` (`deploy/public/deploy.sh:36,264`) and `acp-grafana`
(`:634-644`), both by `az acr build` for Container Apps. The manifest is the interface a build must
produce, which is why it went first.

**Next step.** Build the release images in CI and emit a signed manifest from that build. Until an
image exists, every later step in B, C and D is untestable.

---

## B. Helm production hardening

The checklist run against **rendered** `standard-production` and `high-availability` output rather
than template text. Requirements are the Kubernetes half of PRD §5.2 plus §8 (profiles), §12
(storage) and §13 (security).

| # | Requirement | State | Evidence |
|---|---|---|---|
| 1 | Restricted pod security | **partial** | `runAsNonRoot`, `runAsUser: 10001`, `fsGroup` (`values.yaml:181-183`); `allowPrivilegeEscalation: false`, `drop: [ALL]` (`:185-188`). `grep seccompProfile <rendered>` → **0 hits, exit 1**, and `restricted` requires one. `readOnlyRootFilesystem: false` on all 8 containers (`values.yaml:186`) |
| 2 | Requests **and** limits | **partial** | api, 3 workers, migrate, preflight: both, from the preset (`values.py:72,77`). **ollama and grafana render with no `resources` block at all** — 6 `resources:` in the render, none of them theirs. Both are BestEffort, first to be evicted, and rejected by a namespace LimitRange that requires requests |
| 3 | Temporary storage | **partial** | `ephemeral-storage` request and limit on every ACP tier, floor computed and enforced (`presets.minimum_ephemeral_gib`; `tests/test_packaging_validate.py::test_ephemeral_storage_below_the_computed_floor_is_rejected`). But `presets.py:115-121` says the ×4/×1/×1.5 factors are "DECLARED PLANNING CONSTANTS, NOT MEASUREMENTS", and nothing renders an `emptyDir` with a `sizeLimit` — scratch lands on the node's writable layer |
| 4 | Topology spreading | **weak** | `grep topologySpreadConstraints` → **0 hits, exit 1**. One `affinity` block in the whole HA render: the API's *preferred* anti-affinity, `topologyKey: kubernetes.io/hostname` (`api-deployment.yaml:72-87`), and only when `replicaCount > 1`. Worker tiers running 2–4 replicas in HA get nothing. PRD §8 asks HA for multi-zone; hostname is not zone |
| 5 | Disruption protection | **partial** | `podDisruptionBudget.enabled` is true only for `high-availability` (`values.py:185-188`), so a `standard` API tier running 2–4 replicas has no PDB and a node drain can take all of them. API-only, argued in `pdb.yaml:11-15`. `minAvailable` hardcoded 1 (`values.py:189`), so a 3-replica HA API may be drained to 1 |
| 6 | Service accounts | **weak** | One SA for api, workers, ollama, grafana and both hook Jobs. `grep automountServiceAccountToken <rendered>` → **0 hits, exit 1**; no Role/RoleBinding; no annotations (D1). Nothing here needs the API server, so the token is mounted for no reason |
| 7 | Probes | **satisfied for the tiers that matter, with one hole** | API readiness `/probe/readyz`, liveness `/healthz`, deliberately different and deliberately failable (`_helpers.tpl:211-223`) — fixed by #1798, see *Closed since*. Workers get none, argued (`worker-deployment.yaml:89-95`) and now true of the rendered container. **ollama gets startup+readiness and grafana readiness only — neither has a liveness probe**, so a wedged model runtime is never restarted |
| 8 | Graceful worker shutdown | **satisfied on both sides, untested** | `terminationGracePeriodSeconds: 300` (`worker-deployment.yaml:55`) against an application that drains on SIGTERM (`api/worker_main.py:32,37-38,55-57`). Untestable here: no cluster |
| 9 | GPU only where required | **NOT rendered** | `standard-production` sets `ai.ollama.gpu: true`; `grep nvidia <rendered>` → **0 hits, exit 1**. `ollama.yaml:109-113` carries a comment explaining why "only the limit is set" for `nvidia.com/gpu` — **no line in the template sets it**, and the `if .Values.ai.ollama.gpu` block guards only `nodeSelector` and `tolerations`, which `acpctl values` never emits. So `gpu: true` renders nothing at all and the vision lane silently runs on CPU |
| 10 | No public ingress on any worker | **satisfied** | Rendered Services are `acp-api`, `acp-ollama`, `acp-grafana` only; no worker Service exists. `acp-worker-no-ingress` NetworkPolicy with `ingress: []` renders in all profiles, pinned by `test_packaging_chart.py::test_private_workers_render_a_policy_that_admits_nothing` |
| 11 | No authoritative output on ephemeral storage only | **NOT satisfied** | See below |

**Four defects the rendered-manifest tests were green on**, found on 2026-09-08, and fixed. The
first three by reading the application against the chart rather than the chart against itself; the
fourth by installing it:

- **Default-deny denied DNS, and the egress policy did not open the database.** The
  `-default-deny` policy adds `Egress` to its policyTypes with no egress rule, which denies every
  outbound packet from every ACP pod. The companion `-egress` policy that lets anything back out
  rendered only `if allowedEgress` was non-empty — and even then opened 53 and 443 only, never
  5432 or 6379. So on a cluster that ENFORCES policy, a document with no external sources resolved
  nothing at all, and one with external sources still could not reach Postgres or Redis. The
  installation cannot start either way. Nothing caught it because no cluster anybody had tested on
  enforces NetworkPolicy — and `acpctl doctor` treats a CNI that does **not** enforce as a
  blocker, so the chart required exactly the environment in which it could not run. The reference
  cluster below cannot catch it either (kind's CNI does not enforce), which is why its README
  lists NetworkPolicy enforcement as untested.

- **Every `helm install` of this chart failed, and had always failed.** Helm runs `pre-install`
  hooks BEFORE it creates the release's own resources. Both hook Jobs named the chart's
  ServiceAccount, which is one of those resources — so the ServiceAccount admission plugin
  rejected the Job's pod, the Job controller created none, and Helm gave up after ten minutes on a
  Job at `0/1` with **no pod at all**:

  ```
  Error: INSTALLATION FAILED: failed pre-install: 1 error occurred:
          * timed out waiting for the condition
  ```

  This is the one no amount of reading would have found, and the reason the reference cluster
  below exists: a rendered manifest has no ordering, so `helm template` was clean throughout. It
  was the FIRST thing the first install hit. The hooks now run as `default` and drop the token
  they never used; neither touches the Kubernetes API.

All four are a line or two of template each. What is worth keeping from them is the shape: a
rendered-manifest test compares the chart against itself, so a chart that renders the wrong thing
consistently passes. None was reachable without reading the application the chart deploys, or the
CNI semantics it depends on — and the fourth was not reachable by reading at all.

**A Helm install served the API to anyone who could reach it.** `api/app.py`'s `_access_gate`
middleware is explicitly a no-op when neither `ACP_ACCESS_CODE` nor `ACP_GOOGLE_CLIENT_ID` is set —
its own docstring says "No-op when neither is set (local dev)" — and the chart rendered neither.
Every example document sets `network.publicIngress: true`, so every installation this repository
could describe served every non-public route to anything that reached the Ingress. Not a weak gate;
no gate.

What kept it invisible is a naming near-miss. The contract already *required*
`google-oauth-client-secret` for the Google Drive source, which projects as
`GOOGLE_OAUTH_CLIENT_SECRET` — a variable nothing in `api/` reads. The one that arms the gate is
`ACP_GOOGLE_CLIENT_ID`: a different value with a similar name, required by nothing and mentioned
nowhere. A reviewer scanning the refs for something Google-shaped and authentication-shaped found
one.

Now an ERROR rather than a warning, unlike the object-storage rule above, and the difference is
whether the document can do anything about it: this one is satisfied by a single reference the
chart already knows how to project, so a document that omits it has chosen an open deployment
rather than been unable to describe a closed one. `deploy/public/deploy.sh` has always set one of
the two — "per-user GIS (client id set, passcode off) vs demo (passcode gate on)" — so production
was never in this state and the derived Azure document now records which secret proves it.

**The seam that loses the product's output, found and half-fixed.** `api/blob.py` is the PRIMARY
store for a remediated file's fixed copy (ADR 0010) and decides whether it exists from one
variable, `ACP_BLOB_ACCOUNT`. Unset, `_ENABLED` is false and every function returns `None`.
`deploy/public/deploy.sh:51,411` has always set it on both the API and the worker apps; **this
chart set nothing**. So a Helm install came up healthy, remediated documents, logged that the
corrected copy was stored, and kept each one's digest and byte count while dropping the bytes —
`store.record_remediation` takes the `blob_url is None` branch, there is no BYTEA column (ADR 0010
rejected one deliberately), and there is no filesystem fallback. That is PRD S20.5's acceptance
criterion failing in a way worse than the criterion describes: the artifact does not depend on
ephemeral storage, it reaches no storage at all.

Half-fixed, and the half that is missing is not a packaging problem. The contract now carries
`data.objectStorage.account`, the chart projects it to every workload that writes, and
`acpctl validate` warns — naming the consequence rather than a missing field — when a document
omits it. What no packaging change can supply is an implementation for anywhere but Azure:
`api/blob.py` builds `https://<account>.blob.core.windows.net` and authenticates with
`DefaultAzureCredential`, with no endpoint override, no key-based path and no S3 client anywhere in
`api/`. PRD S7's cloud mapping lists S3 and Cloud Storage for the other platforms; nothing
implements them, and `boto3` is not in `api/requirements.txt`. So **acceptance scenario 4's
"artifact persistence" cannot pass on a non-Azure target today**, and the second warning
(`objectstorage.azure-only`) says so to any document that names an account off Azure. Adding an
S3-compatible backend is an application change and an owner decision, not one to take from here.

**One more of the same family, analysed and NOT fixed**, because the fix cannot be tested here.
With `secrets.provider: key-vault` the chart renders an `ExternalSecret`, which is a normal
resource, and the pre-install hook Jobs mount the Secret the External Secrets Operator syncs from
it. Same phase ordering, same result: on the ESO path the migration Job starts before the Secret
exists and, with `backoffLimit: 0`, fails immediately rather than waiting. Making the
`ExternalSecret` a pre-install hook would order the OBJECT correctly and still lose the race, since
ESO syncs asynchronously and Helm cannot wait on a CRD it does not understand. The reference
cluster uses `provider: kubernetes` with an operator-supplied Secret, so it cannot exercise this
path and a fix shipped from here would be untested. Recorded rather than guessed at.

**They were all the same defect, and it now has a test.** Seven findings in one day — the worker
command, the readiness probe, the pre-install hook ordering, the egress policy, `ACP_BLOB_ACCOUNT`,
`ai.ollama.gpu`, the access gate — are one shape: the chart deploys a workload that reads something
the chart never set, or sets something nothing reads. Every one was silent, every one was green
under a rendered-manifest test, and every one was found by hand. Finding the eighth by hand is not
a plan.

`tests/test_packaging_seams.py` pins both directions. The chart-sets-but-nothing-reads set is
DERIVED from the render and compared against a table with a reason per entry, so a new one fails in
seconds and a stale entry fails too. The application-reads-but-the-chart-omits list is curated —
resolving what `deploy.sh` sets means resolving shell variables through their defaults, and a
parser for that would be a second implementation of bash that goes wrong quietly — but every entry
is checked against the three facts that make it a gap, so it cannot carry a false claim, and
closing a gap fails until the entry is deleted.

Nine gaps are recorded there now, and the guard has already closed one of its own entries.

**The drain window, fixed.** `api/core.py:1943` defaults `ACP_SHUTDOWN_DRAIN_SECONDS` to 20 and the
chart never set it, while `worker-deployment.yaml` asked Kubernetes for 300 — so a rolling upgrade
abandoned a document mid-remediation and the pod then idled for the remaining 280 seconds. The
template's own comment said a worker "gets time to finish it" and called the platform default of 30
too short; it got 20. The two numbers are one decision and are now derived from each other, with
production's own 60-second headroom (540 inside a 600s grace) as the constant. Leaving the entry in
the guard failed the guard, which is the loop working.

**One underscore from a security control, fixed.** The chart rendered `ACP_ENVIRONMENT` — a name
nothing in `api/` reads — while `api/core.py:87` computes `IS_PROD` from `ACP_DEPLOY_ENV`, and
`IS_PROD` is what forces `TEST_BYPASS_ENABLED` off: the X-E2E-Key and X-Demo-Key gate bypasses are
refused in production regardless of the opt-in that enables them. That file records the same
failure happening once already — *"IS_PROD stayed False on the public demo, and the X-E2E-Key
bypass stayed live"* — because the variable operators were told to set never reached the container.
The bypass is fail-closed now, so nothing was open; what was true is that an installation enabling
it for staging and promoting the same values to production kept it, because the chart gave the
application no way to know which it was. Renamed rather than duplicated, since the old name was
read by nothing and a workload carrying both would leave a reader guessing which one is live. The
guard failed in BOTH directions until both of its entries were updated.

That is the third naming near-miss of the day, after `GOOGLE_OAUTH_CLIENT_SECRET` against
`ACP_GOOGLE_CLIENT_ID` and `OBJECT_STORAGE` against `ACP_BLOB_ACCOUNT`. The pattern is worth
naming: a chart that invents its own variable names produces workloads that look configured and
are not, and the resemblance is what stops anybody looking twice.

**Langfuse tracing could never start, fixed.** `api/lf.py:23` is
`_ENABLED = bool(_HOST and _PK and _SK)` and the chart projected the secret key alone — so the
`langfuse-secret-key` reference the contract *requires* bought one of three, and an operator who
provisioned Langfuse saw no traces and no error. The contract now carries
`observability.langfuse.host` (an endpoint, so a document field rather than a reference) and
requires both keys, because requiring one of three is not a weaker version of requiring three: it
is a rule that cannot do the thing it was written for.

**And it surfaced a v1alpha1 gap worth recording rather than working around.** `self-hosted` means
"in-cluster" everywhere else in this contract — for Postgres and Redis the chart *fails the render*
rather than provisioning one — so `acpctl inventory` plans `acp-langfuse` as an in-cluster service
while the chart renders nothing for it, and `test_the_derived_production_document_plans_nothing_it_would_not_install`
enforces the difference. Production's Langfuse is neither: it is a Langfuse the customer runs, as
its own Azure Container App, outside the release. There is no mode that says *self-hosted, but not
by this release*, which is why the derived Azure document declares no langfuse block at all — the
honest options were to say something false or to say nothing, and it says nothing. A `mode:
external` in v1alpha2 is the fix; inventing one here would have been a contract change smuggled in
under a wiring fix.

**Restricted pod security, now enforced rather than described.** `runAsNonRoot`,
`allowPrivilegeEscalation: false` and `capabilities.drop: [ALL]` were all present and the
`seccompProfile` was not — and its absence means `Unconfined`, which is what the standard exists to
refuse. Three quarters of a standard is not the standard. It is set now, and more usefully the
reference cluster labels its namespace `pod-security.kubernetes.io/enforce=restricted`, so the API
SERVER decides: a pod that does not meet it is rejected at admission and the install fails. That is
the difference between this and a rendered-manifest test, and it is the second claim (after
NetworkPolicy, which kind cannot enforce) that the disposable cluster turns from text into a
decision something else makes.

Enforcing it found its first pod immediately, and not one of the chart's: the reference
Postgres and Redis were written before the label existed, default to running as root, and were
rejected outright. Their Deployments were created and never produced a pod, so the run died three
minutes later on a `rollout status` timeout with nothing to describe — while the API server had
named all four missing fields as a WARNING on the apply. They carry restricted contexts now, and
the apply runs `--warnings-as-errors` so the message that names the fields is the message that
fails.

**`readOnlyRootFilesystem` is `false`, and that is now a recorded decision rather than an
oversight.** Every runtime write the application makes goes to `$TMPDIR` — per-document scratch in
`api/scanner.py`, `api/handlers.py`, `api/proposals.py` and the PDF engine, the LibreOffice user
profile (`api/render.py:106`), the .NET analyser's `_o.json`, `remediated-<name>` beside its input,
tesseract's scratch images — all of which an `emptyDir` at `/tmp` would cover. One write does not:
`PUT /rubric` used to write `<repo>/config/rubric.active.json` INTO THE IMAGE, so a read-only
root turned an owner-only admin endpoint into a 500. **THAT WRITE IS GONE**: the rubric is stored
in `app_settings` now, so the application-side blocker this default existed for no longer exists.
What remains is packaging work rather than an application change — an `emptyDir` at `/tmp` plus
`HOME`, `XDG_CACHE_HOME` and `DOTNET_CLI_HOME` pointed into it — and the chart renders no volumes
at all today. So the default stays `false` until that lands, and
`test_the_shared_root_filesystem_is_writable_and_that_is_deliberate` pins both halves: the value,
and the write it exists for.

**THAT WRITE IS ALREADY BROKEN, INDEPENDENTLY OF ANY OF THIS, AND IT IS NOT A KUBERNETES
PROBLEM.** Tracing it far enough to judge the read-only question turned up something larger.
`PUT /rubric` writes to the container filesystem of whichever API replica served the request, and
`core.active_rubric()` reads that same path at request time (`api/core.py:538`). The chart renders
no volumes, so the path is that one container's ephemeral layer. Three consequences follow, and
the endpoint's own docstring rules all three out — it calls the rubric "the GLOBAL scoring policy"
and gates the route on owner-only precisely because it decides "how every tenant is scored":

  - Other API replicas keep the previous rubric. standard-production's floor is TWO.
  - EVERY WORKER CONTAINER keeps it too, and workers are where scoring happens: `worker_main`
    calls `core.start_workers()`, the handlers call `core.active_rubric().hash`
    (`api/handlers.py:2379,4171,4236,4468`), and no worker ever receives the PUT. So the change is
    invisible to the tier that applies it even on a single-replica API.
  - It is lost on restart or redeploy, because nothing persists it.

`rubric_hash` is recorded against scans, so pods scoring under different policies also record
different hashes for the same configuration. This affects Compose and Container Apps as much as
Kubernetes — anything running the worker as a separate container, which is all three — so it is
pre-existing rather than something the packaging work introduced.

The fix is the mechanism the application already has for exactly this: `core.store.set_setting`
/ `get_setting`, which is how `ai_vision_provider` is stored and read. That is an application
change and an owner decision, not a packaging one, and it is recorded here because it is the
blocker under the blocker: with the rubric in the database, `readOnlyRootFilesystem: true` costs
nothing but an `emptyDir` at `/tmp` and three environment variables.

Turning it on later also needs `HOME`, `XDG_CACHE_HOME` and `DOTNET_CLI_HOME` pointed inside the
writable mount. UID 10001 has no passwd entry — none of the Dockerfiles contains `USER`, `useradd`
or `HOME`, and the UID comes only from `values.yaml` — so `expanduser("~/.dotnet")`
(`api/scanner.py:59`) and fontconfig both resolve somewhere unverified today.

**The failure mode is why this is worth writing down rather than trying.** An unwritable scratch
directory does not crash anything. `render_page_png` returns `None` on any exception
(`api/render.py:78`), `_office_to_pdf` returns `None` (`api/render.py:112`), and `_analyse_office`
turns `OSError` into an engine-error bucket that scores as `uncertain` (`api/scanner.py:4360`).
Office documents would quietly degrade to `uncertain` with no startup signal and no error anybody
sees. The one loud failure is the sqlite bootstrap at `/app/acp.db`, which the chart cannot reach
because `DATABASE_URL` is a required reference.

The override that was supposed to protect Ollama from all this did not work. `ollama.yaml` pinned
`readOnlyRootFilesystem: false` with `merge (dict "readOnlyRootFilesystem" false)
.Values.securityContext` — and `merge` is mergo underneath, which overwrites a destination value
that is its type's ZERO. `false` is. So the override was discarded exactly when the shared value
was `true`, which is the only case it exists for; it read as working because both were `false` and
agreed. It is `deepCopy` + `set` now, and
`test_ollamas_root_stays_writable_whatever_the_shared_value_says` renders with the shared value
forced on. The comment beside it claimed the shared context "sets it true", which had never been
so — a reader deciding whether this chart hardens its root filesystems would have concluded it
does.

**The chart's own network policy blocked the chart's own preflight check, and `helm install`
failed on any cluster that enforces NetworkPolicy.** Replacing kindnet with Calico made the
policies enforceable for the first time, and the very next install failed:

    Error: INSTALLATION FAILED: failed post-install: job acp-preflight failed: BackoffLimitExceeded
    [preflight] could not reach http://acp-api:80/readyz: <urlopen error timed out>

The preflight Job carries this chart's selector labels, so the `-egress` policy applies to it —
and that policy lists the ports ACP needs to leave the CLUSTER on (53, 443, 5432, 6379, 6380).
Neither the API's service port nor its container port is among them, because reaching your own API
is not egress in the sense the list was written for. The request was dropped, the hook exited 1,
and Helm failed the release. Every production cluster enforces NetworkPolicy; eleven green runs
said nothing about it because kindnet does not.

The fix is a second egress rule scoped to the API pods rather than a port opened globally — `to`
plus `ports` is an AND, so ACP's pods may reach ACP's API and nothing else. Both the service port
and the container port are named: a ClusterIP connection is DNATed to the backend before it
leaves, and which of the two a given CNI matches on is not something this chart should depend on.

TWO CLAIMS DIED WITH IT. This report's workstream C row called the preflight hook "advisory
(`backoffLimit: 0`, post-install)", and the hook's own docstring said it was "a report,
deliberately not a gate" that "does not block". Helm has no hook failure policy: a hook that exits
non-zero fails the release, and that container exits 1. It is a gate, it always was, and nobody
had seen it act as one because nothing had ever made it fail. Making it exit 0 to match the
description would have converted the one thing that caught this into a check that cannot fail.

**What the reference install never creates, counted rather than guessed at.** The reference
document renders NetworkPolicy, PodDisruptionBudget, ServiceAccount, one Service, four Deployments
and two Jobs. The standard-production example renders all of that plus a HorizontalPodAutoscaler,
an Ingress, an ExternalSecret, two ScaledObjects, a TriggerAuthentication, two more Services and
the Ollama and Grafana Deployments — and none of those had ever been submitted to an API server.
The annotation-type defect below was in six render sites and this install exercises three of them,
so the same bug in `ollama.yaml` or `grafana.yaml` would have shipped past a green job.

A server-side dry run of the full-featured render closes that, costs seconds, and is the same kind
of evidence as the install: the API server validates the schema and runs admission, so the dry-run
namespace carries the restricted label for the same reason the real one does. Nothing is
persisted. ExternalSecret, ScaledObject and TriggerAuthentication were skipped at first, needing CRDs the
cluster did not have. THE CRDs ARE INSTALLED NOW — the definitions only, not the operators, which
is the right amount: `--dry-run=server` validates a custom resource against its
CustomResourceDefinition's schema and needs nothing else. Installing KEDA and External Secrets
themselves would test their behaviour rather than these manifests, take minutes rather than
seconds, and remove two blockers `acpctl doctor` is correct to report on a real cluster. So
nothing is skipped, and the three are still NAMED — a render that stopped producing them would
otherwise leave the step passing over a smaller set and saying nothing about it.

What it still does not establish: that these objects DO anything. An Ingress that validates has
not routed a request, and an HPA that validates has not scaled a tier. Schema and admission are
what a dry run can answer.

**The upgrade step found a defect on its first run, and it was not an upgrade defect.**
`toYaml` preserves YAML's types, and both `annotations` and `nodeSelector` are `map[string]string`
in the Kubernetes API. A value that parses as a number or a boolean renders unquoted, passes
`helm template` and `helm lint`, and is rejected by the API SERVER:

    cannot patch "acp-api" with kind Deployment: "" is invalid: patch: Invalid value: "{…}":
    json: cannot unmarshal number into Go struct field
    ObjectMeta.spec.template.metadata.annotations of type string

It surfaced on an upgrade only because that is where the probe annotation is set, to
`$GITHUB_RUN_ID`, which is all digits; an install carrying the same value fails identically.
`--set-string` is not the fix, because the operator most likely to hit this is writing a values
FILE — `build-number: 1234` is an int before helm sees it, and there is no per-key string flag for
a file. So `acp.stringMap` quotes every value at all six render sites, and the CI step keeps using
plain `--set` so it goes on exercising the numeric path.

Worth noting what this says about the render tests. They parse the rendered YAML and assert on the
result, so an annotation rendered as an integer arrives as a Python `int` and every assertion about
it still passes — the defect is in the TYPE, which is exactly what a round-trip through a parser
erases. Only something that submits the manifest can find it.

**`acpctl doctor` evaluates the DOCUMENT, and the job installs something else.** On the
reference cluster doctor reports `capacity.floor` as a blocker — five `small` pods need 5 CPU and
the runner has 4 — and the install then succeeds, because the job layers
`packaging/reference/kind/runner-resources.yaml` to lower the requests. Both are correct. doctor
is right about the document as written; it is describing a deployment nobody is installing,
because it takes no values overlay and `check_capacity` is a pure function of the values it is
handed. Any operator installing with `-f overrides.yaml` gets the same mismatch, and a preflight
tool that is routinely wrong in the safe direction is one people learn to skip. Giving `doctor`
the same `-f` the install uses is the fix; it touches `cli.py`, which #1796 also edits, so it is
recorded rather than taken.

The step that runs it was decorative until now — `|| true` with nobody reading the output, so
doctor could have stopped producing findings entirely and the job would have gone green. It now
asserts the exact two: `capacity.floor` FAIL and `networkpolicy.enforcement` UNKNOWN, with nothing
else non-pass. Writing that down corrected the step's own comment, which had named NetworkPolicy
as the expected *blocker*: on kind it is UNKNOWN at WARNING severity, because kindnet appears in
neither the enforcing nor the known-non-enforcing CNI list, so it does not make `ok` false. The
blocker was the capacity one, and no comment mentioned it.

**The cluster now upgrades as well as installs, which is a different claim.** Every way this
chart could fail to upgrade is invisible to `helm template` AND to a first install, and each one
strands a running installation rather than a test cluster. `spec.selector` is immutable, so a
selector label that moves with the release installs perfectly and makes the first upgrade fail
with a message about a field that cannot be changed. A hook Job is a named object, so without
`before-hook-creation` in its delete policy the second release finds the first one's Job still
there. And the migration hook is `pre-install,pre-upgrade`, so an upgrade runs it against a schema
it has already applied — a non-idempotent migration fails there and nowhere earlier.

The step changes the pod template rather than re-applying the same values, because `helm upgrade
--wait` exits 0 for a release that replaced nothing: it sets an annotation, checks the release
reached revision 2, and then looks for that annotation on the running pods. A render test cannot
express "unchanged across releases" from one render, so the selector half is also asserted by
rendering the chart at two different versions and comparing.

**The disruption budget was gated on the profile name, not on what the profile runs.**
`values.py` read `"enabled": rt["profile"] == "high-availability"` while the comment directly
above it described the rule as replica count — and standard-production runs a FLOOR OF TWO API
replicas. It got no budget, so `kubectl drain` on the node holding both evicted both, which is
what a cluster autoscaler does during a routine node upgrade: the failure a second replica is
bought to prevent, on the profile most installations will use. The test covering this asserted the
defect in its own name — "high availability gets one and standard does not" — and was green
throughout, because it named the profile and never asked what the profile ran.

It is the replica floor now, which is what the comment always said. A floor of one still gets
nothing, and that half is not symmetry for its own sake: `minAvailable: 1` against one replica
permits no eviction at all, so it does not protect the tier, it stops the node being drained. The
worker tiers still get none, deliberately — a worker evicted mid-document returns its job to the
queue, and budgeting a tier designed to be interrupted blocks drains for no gain.

**Zone spreading, and what the anti-affinity was not doing.** The API's existing rule is
`preferredDuringScheduling` across `kubernetes.io/hostname`: it asks for different NODES and says
nothing about zones, so three replicas can land on three nodes in one availability zone and
satisfy it completely — while losing a zone is the failure a multi-replica tier is bought to
survive. Every tier that runs more than one pod now carries a `topology.kubernetes.io/zone`
constraint with `maxSkew: 1`; Ollama and Grafana do not, being one pod by construction.

`whenUnsatisfiable` is `ScheduleAnyway` on every profile, `high-availability` included, and that
is a deliberate limit rather than a default nobody chose. `DoNotSchedule` excludes nodes that do
not carry the topologyKey LABEL, so on a cluster whose nodes have no zone label — every kind and
k3d cluster, any single-zone install, and the reference cluster this chart is installed on — there
is no eligible node and every replica stays Pending forever. Without `matchLabelKeys` (1.27+,
against `MINIMUM_KUBERNETES` of 1.23) the constraint also counts the outgoing ReplicaSet during a
rolling update and can wedge an update against its own predecessors. PRD S4 says a target is not
supported because Helm renders for it, so the hard value is one `--set` away for an operator who
knows their nodes are labelled, and the chart asserts no multi-zone survival it has not shown.

**The reference cluster cannot prove any of this, and says so.** One node, no zone labels: the
constraint renders, admits, and has one domain to balance across. What it proves is that the
manifests are accepted and the pods still schedule — not that a zone loss is survivable. That
needs a multi-zone cluster, which is a billable shared environment and an owner decision.

The trap on the way in is worth recording because nothing catches it. The first draft built each
constraint's selector from `app.kubernetes.io/component`, which is `worker` on all three worker
Deployments — so the worker constraints would have selected the union of the tiers. A topology
constraint whose selector matches the wrong pods, or none, is not an error: it is satisfied
vacuously, renders correctly and spreads nothing.
`test_every_spread_constraint_selects_the_pods_it_is_attached_to` asserts each selector is a
subset of the labels its own pod template carries.

**What is missing.** No PersistentVolumeClaim and no volumes at all —
worker scratch is the node's ephemeral storage, bounded only by the limit above. No
backup or restore Job, which PRD S5.2 lists as part of the Kubernetes package. Langfuse is deployed
ungated by Compose and rendered by nothing in the chart — asserted, deliberately, by
`test_packaging_chart.py::test_compose_deploys_what_the_chart_omits`.

**The blocking gap this section used to describe is closed, and saying so precisely matters more
than saying so.** It read: "there is no reference Kubernetes version, and no cluster to render
against… There is no `kind`, `k3d` or `minikube` reference anywhere in the repository; CI installs
helm solely so `helm template` and `helm lint` can run. Every hardening claim above is therefore a
claim about text." Every sentence of that is now false. `packaging/reference/kind/` installs this
chart on `kindest/node:v1.31.4`, pinned to the digest a run recorded, on every packaging pull
request, and the hardening claims above are decided by an API server rather than asserted about
YAML.

`doctor.MINIMUM_KUBERNETES = (1, 23)` is still a floor derived from when `policy/v1` and
`autoscaling/v2` went stable rather than a version anything is supported on, and 1.31.4 is a
version the chart RUNS on rather than one anybody has certified. Naming a supported distribution
is PRD §4 and an owner decision, not a task.

Two of `doctor`'s three silent prerequisites are no longer tested only against
`tests/packaging_kubectl_fake.py`. An enforcing CNI is real — Calico, which is why the egress
defect above surfaced at all — and KEDA's and External Secrets' CRDs are installed so their
custom resources are validated by the API server rather than skipped. What is still fake is the
OPERATORS: nothing has watched a `ScaledObject` scale a tier or an `ExternalSecret` materialise a
Secret, and installing them would test their behaviour rather than this chart's manifests.

**What remains a claim about text, and it is the sharpest one left.** "No authoritative output
lives only on ephemeral storage" (PRD §12) is asserted by
`tests/test_packaging_inventory.py::test_worker_scratch_is_declared_and_disposable` against the
inventory's declaration. Nothing has observed where a remediated file actually lands, because no
document has ever been scanned or remediated on this cluster — that is workstream C, and the
`ACP_BLOB_ACCOUNT` defect (an installation that produced remediated documents and dropped them)
is the reminder of what that gap can hide.

**Next step.** Not another cluster capability. The remaining workstream B items are each blocked
on a decision rather than on work: `readOnlyRootFilesystem` on moving the rubric write out of the
container, a backup/restore Job on RTO/RPO and retention, and a supported-distribution claim on
PRD §4.

---

## C. Portable acceptance suite

**In flight in PR #1796**, which is this branch: `packaging/acceptance/` (runner, scenarios, report
schema, a fake execution backend) and `tests/test_packaging_acceptance.py` are being written in the
same change as this file and are **not assessed here**. What follows is the gap the suite has to
close, stated against the rest of the tree.

**What exists to write scenarios against.** 16 packaging test files run in CI, asserting on
*rendered manifests* rather than template text; `inventory.LANE_JOB_TYPES` pins the queue lanes to
`api/core.py`; `acpctl status` reads a running release and reports health and drift with documented
exit codes (`tests/test_packaging_status.py`, 29 cases against a fake kubectl). The closest thing
to an in-cluster probe is `preflight-job.yaml`, a post-install hook that reports connectivity and
does not gate (`backoffLimit: 0`, `hook: post-install,post-upgrade`) — advisory by design.

**C1 — no test in this repository stands up anything.**
`grep -rln "docker compose\|docker-compose" tests/ --include=*.py` returns three files
(`test_bench_harness.py:14`, `test_monitor.py:440`, `test_packaging_chart.py:1098`), and all three
read the compose YAML as **text**. Nothing starts a container, a stack or a cluster; today's suite
covers the *render*, which is one precondition of the first PRD §19 scenario. The acceptance work
in flight is built on a fake execution backend for exactly this reason.

**C2 — the API tier's declared autoscaling signal cannot exist.** The rendered HPA carries a `Pods`
metric named `acp_concurrent_requests`. That string appears exactly twice in the repository — the
template that emits it (`autoscaling.yaml:54`) and `doctor.py:369`'s advice to install an adapter
that publishes it. There is no `prometheus_client` import and no `/metrics` route in `api/`
(`grep -rn "prometheus_client\|'/metrics'" api/` → **exit 1, 0 hits**; control `grep -rln readyz
api/` → 15 files). No adapter can publish a metric the application does not expose, so the API tier
degrades to CPU alone — which PRD §11 permits only as a *secondary* signal.

**C3 — the plan promises a service the chart never installs.** `acpctl plan` lists `acp-langfuse`
under resources it would create (`inventory.py:343`); the render contains no Langfuse workload,
while the chart *does* project `langfuse-secret-key` into the API. Known and pinned by
`test_packaging_chart.py::test_compose_deploys_what_the_chart_omits`. It is a contract decision, not
an omission to fill, and it needs deciding before an acceptance run scores it.

**Next step.** One target, one cluster, one end-to-end assertion: API becomes ready, a worker claims
a job, a remediated artifact lands in object storage and is **readable after the pod is deleted**.
That last clause is the only thing that tests B11.

---

## D. `acpctl` lifecycle

**In flight in PR #1796:** `install`, `uninstall`, `support-bundle` and their state handling
(`packaging/cli/acpctl/install.py`, `uninstall.py`, `state.py`, `helm.py`,
`packaging/docs/lifecycle.md`) are being written in this same change and are **not assessed here**.
`cli.py:38-43` now lists only `upgrade`, `rollback`, `backup` and `restore` as not implemented, each
parsing its arguments and returning 2 so none can become an accepted-and-ignored no-op.

**What exists and is assessable.** The read-only commands: `init`, `validate`, `plan`, `inventory`,
`values`, `release`, `adapter`, `doctor`, `status`. Exit codes are documented and tested —
`validate` 0/1; `doctor` and `status` 0/1/2 with 2 reserved for "the cluster could not be reached,
so nothing was established", which is the distinction a retry loop needs. The read boundary is
enforced rather than asserted: `cluster.py`'s kubectl allow-list contains no mutating verb
(`tests/test_packaging_doctor.py::test_acpctl_refuses_to_run_a_mutating_kubectl_verb`, parametrized
over a dozen), and what can change a cluster lives behind `helm.py`'s own narrower list.

**D1 — `secrets.workloadIdentity` is accepted by the validator and rendered by nothing.**
`spec.py:_rule_required_secrets` treats a name under `workloadIdentity` as satisfying a required
reference, deliberately, because production reaches Blob through a managed identity and holds no
storage credential. The derived production document uses it
(`packaging/docs/azure-current.acp-deployment.yaml:86-87`). But
`grep -rn workloadIdentity packaging/chart/acp/ packaging/cli/acpctl/values.py` → **exit 1, 0
hits**, and the rendered ServiceAccount carries no annotations at all. `serviceaccount.yaml:8-16`
calls itself "the ONE place the platform reaches into the workloads"; `acpctl values` emits no
`serviceAccount` key, so that place is always empty. A document that validates on the strength of
workload identity installs a release with neither a credential nor an identity.

**D2 — nothing in the lifecycle path can be exercised here.** `doctor` and `status` both exit 2
without a cluster, and no registry holds an artifact to pull. The lifecycle work landing in this
change is reviewable as code and not yet as behaviour — the same sentence as C's, for the same
missing pieces.

**Next step.** Emit `serviceAccount.annotations` from the adapter, with a test that fails when a
`workloadIdentity` entry produces no annotation. Then exercise `install` against the first real
cluster, against a real release manifest.

---

## What blocks a disposable-cluster acceptance run today

**Four of the seven items this list opened with are done**, and the list is kept with them struck
through rather than deleted, because the shape of the dependency chain is the useful part and a
list that only ever grows shorter hides what was actually hard.

1. ~~**The chart and the plan must agree on the artifact set.**~~ Done. The `ACPRelease` contract
   reconciles the plan's eight names, the chart's four image references and the one artifact this
   repository builds, with `serves` and `chartImages` naming which is which
   (`packaging/schema/acp-release.schema.json`, `tests/test_packaging_release.py`).
2. ~~**Something must build the images the chart names.**~~ Done for a TEST, not for a release. The
   reference job builds the application image from the checkout and `kind load`s it, which is why
   item 3 turned out not to be a prerequisite at all. Nothing yet builds, signs or SBOMs a
   RELEASED artifact — that is workstream A's remaining half and is what item 7 depends on.
3. ~~**A registry the acceptance run can pull from.**~~ Not needed, and finding that out was worth
   more than solving it. `kind load docker-image` with `pullPolicy: Never` puts the image on the
   node without any registry, so a disposable-cluster run needs no push target and no credentials.
   A registry is still required for a release, which is item 7's problem rather than this one's.
4. ~~**A disposable cluster in CI.**~~ Done. `packaging/reference/kind/` and
   `.github/workflows/packaging-kind.yml` install the chart on `kindest/node:v1.31.4` on every
   packaging pull request, and the Summary above says exactly what that does and does not
   establish.
5. **`acpctl install`.** Still the gate on everything from scenario 3 onward — queue processing,
   restart mid-job, scale-down, upgrade, restore. An open pull request is building it together
   with the acceptance suite; nothing here should be read as its being done.
6. **The acceptance report format**, without which ten passing scenarios produce ten passing
   scenarios and no artifact anybody can compare across runs. Same pull request as item 5.
7. **Digest resolution and signature verification**, which is the point at which the run stops
   being a smoke test and starts being evidence about a specific release. Unchanged, and now the
   only item with no work in flight: it needs a build that produces a signed manifest, which needs
   a registry, which is an owner decision rather than a task.

What the remaining three have in common is that none of them is about the CHART any more. Items 5
and 6 are the lifecycle command and its output; item 7 is the supply chain. Workstream B's
questions are answerable on the cluster that now exists.

## Not in scope for the MVP

- **The AKS adapter.** `packaging/docs/azure-adapter.md` specifies what an adapter must create and
  emits no Terraform or Bicep by design. `deploy/public/` keeps deploying Container Apps, and PRD
  §22 forbids replacing it before parity is demonstrated. Nothing here proposes retiring
  `deploy/public/` or `deploy/compose/`.
- **On-prem certification.** PRD §4 excludes supporting arbitrary Kubernetes distributions without
  certification tests; the MVP validates one reference version, not a distribution matrix.
- **EKS and GKE.** PRD §21 phase 4. `presets.SUPPORT_STATUS` marks both `planned` and should keep
  saying so.
- **Air-gapped bundles.** PRD §17, phase 5. It depends on signed images and SBOMs, so it is
  downstream of workstream A rather than parallel to it.

---

`verified` would mean acceptance evidence from a real cluster. When this report was written
nothing had any. That is no longer true, and the correction matters in both directions.

WHAT THE DISPOSABLE CLUSTER NOW ESTABLISHES, on every packaging pull request: the chart installs
from a document `acpctl` produced; every tier rolls out; the three worker tiers register and
heartbeat through the API; `acpctl status` reports no drift beyond the one expected release-tag
difference; the release upgrades to a second revision with the pods actually replaced; every pod
is admitted by a namespace enforcing the restricted Pod Security Standard; and the manifests this
install does not create — Ollama, Grafana, the HorizontalPodAutoscaler, the Ingress — pass schema
validation and admission under a server-side dry run. Four defects were found this way that every
rendered-manifest test was green on.

WHAT IT STILL DOES NOT ESTABLISH, and none of it should be read as `verified` for a customer:
`kindest/node:v1.31.4` is a version this chart RUNS on, not one anything is supported on. One node
means zone spreading has one domain, the PodDisruptionBudget is never tested by a drain, and
NetworkPolicy — enforced by Calico since 2026-09-08 — has no cross-node path to exercise. No document has been scanned, assessed or
remediated on it, so nothing here is evidence about the application doing its work — that is
workstream C. And the images are built from the checkout under a local tag, so none of this is
evidence about a released artifact.

## Progress (PRD §9 shape)

`verified` is still used for **nothing**, and the paragraph above is why that is not a contradiction:
the disposable cluster establishes that the chart installs, upgrades and comes up healthy, which is
evidence about the PACKAGE. `verified` in this table means a target passed the portable acceptance
suite — the ten scenarios, including a document actually scanned, assessed and remediated — and no
target has done that.

| Target | State | Evidence | Blocker | Next action |
|---|---|---|---|---|
| Release artifacts | in progress | `ACPRelease`, `acpctl release verify`, `--release` on `values`/`plan` (#1797; `tests/test_packaging_release.py`, 37 cases) — a manifest reconciles the plan's eight names, the chart's four components and the built artifacts, and renders every image by digest | Nothing builds, signs, SBOMs or scans an artifact, so no real manifest exists and CI has no release to fail on. Scanning and provenance are not even expressible in the schema | Build the images in CI and emit a signed manifest from that build |
| Helm hardening | in progress | Requests/limits with `ephemeral-storage` on every workload; restricted pod security **enforced by the API server on the disposable cluster**, not merely rendered (#1808); multi-replica tiers placed, and the chart proven to **upgrade** as well as install (#1809); `terminationGracePeriodSeconds: 300` with a matching drain window (#1805); no worker Service; `doctor` blocks on KEDA, CNI and ESO. Two silent defects closed by #1798 | `kindest/node:v1.31.4` is a version the chart RUNS on, not one anything is supported on — naming a supported distribution is PRD §4 and an owner decision. Zone spreading is soft on every profile and unprovable on a one-node cluster; no `readOnlyRootFilesystem` (the `PUT /rubric` blocker is cleared; it now needs a writable `/tmp` mount); no backup/restore Job | A backup/restore Job, which needs RTO/RPO and retention decided first |
| Acceptance suite | in progress | **Run against the disposable cluster on every packaging PR** (`packaging-kind.yml`, runs 34233469967 and 34234894950). MEASURED there: the API is ready and names its build (`0.0.0-kind.46`); all three worker tiers register and heartbeat; and **6 documents were queued and processed by the worker tier** — the first documents this packaging work has moved through a real installation | Three MVP scenarios cannot be answered at all, because the surfaces they read do not exist in any build: `/scans/{sid}/artifacts` (PRD §12's durable-output inventory), `/admin/audit-events` and `/admin/support-bundle` (PRD §13). They report `unknown`, never pass, so **no MVP claim is reachable until those three ship** — that is now the concrete blocker, measured rather than predicted. kind itself certifies nothing: no registry, so no digest to pin | Serve the three surfaces; then the same job answers the MVP scenarios end to end |
| Lifecycle | in progress | `install`/`uninstall`/`support-bundle` **in flight in #1796**, not assessed here. Read-only commands ship today; `workloadIdentity` renders nothing (D1) | No image, no cluster: `doctor`/`status` exit 2 here | Emit `serviceAccount.annotations`; then exercise `install` against the first real cluster |
| AKS | not started | `SUPPORT_STATUS["azure"] = "planned"` (`presets.py:68-75`). `deploy/public/` deploys Container Apps, a different topology (ADR 0048) | Everything above, plus a billable environment | Run the acceptance suite against AKS once one exists; do not rename the status before that |
| On-premises | not started | `SUPPORT_STATUS["onprem"] = "planned"`; `onprem` is `self-hosted`-only, which is the mode the chart refuses to render without an override | Which distribution gets certified first is a customer decision | Pick the distribution, then treat it as a second acceptance target |

---

## Stop-and-ask conditions this work touches (PRD §10)

Human decisions. Each is left open deliberately; none is blocked on engineering.

| Condition | Why it is a decision | State |
|---|---|---|
| Provisioning a billable cloud environment for the acceptance run | Cost and blast radius; see the ask at the top | **outstanding** |
| Which on-premises Kubernetes distribution is certified first | PRD §4 excludes "arbitrary Kubernetes distributions without passing certification tests", so the first one is a commitment to a customer's cluster shape — it needs a customer signal, not a preference | **outstanding** |
| RTO, RPO and backup retention | PRD §8/§16 make these customer-defined. `grep -n "rto\|rpo\|restoreTest" packaging/schema/acp-deployment.schema.json` → **exit 1**; the only backup field is `backupRetentionDays` (`:296`), so neither is expressible and neither is checkable | **outstanding** |
| What `self-hosted` means — operator-provisioned or chart-provisioned data services | ADR 0048's addendum raises it and explicitly does not decide it; today it means `regulated` does not render without an override | **outstanding** |
| Whether `acp-langfuse` belongs in the contract at all | Compose runs it, production never has, the chart projects its credential (C3); which side moves is a product decision | **outstanding** |
| Hostname egress enforcement | `networkpolicy.yaml:72-87`: NetworkPolicy matches IPs, not names. A real allow-list needs Cilium `toFQDNs` or an egress proxy — a cluster requirement to impose on a customer | **outstanding** |
| Measuring the storage expansion factors | `presets.py:115-121` states ×4/×1/×1.5 are unmeasured. Measuring changes every plan's floor | **outstanding** |
| Whether worker tiers get PDBs | `pdb.yaml:11-15` argues API-only because a drain that cannot complete is its own incident. Defensible; an HA customer may disagree | decided, revisit with a customer |
| Telemetry off Azure | `acpctl validate` warns that `local` has no implementation — `api/telemetry.py` configures the Azure Monitor distribution only, with no OTLP exporter. PRD §14 requires regulated installations to collect locally, so a customer-Kubernetes install collects nothing today | **outstanding** |

---

## What is asserted here without having been run

Everything else above is an observed command with its exit code, or a cited line.

- **KEDA/ESO CRD-absent behaviour** (prerequisites rows 1 and 3): that a missing CRD fails the apply
  while a missing *controller* fails silently is reasoned from the API-server contract, not
  observed. No cluster.
- **PodSecurity `restricted` rejection**: the absence of `seccompProfile` is verified in the
  rendered output; that a `restricted`-enforcing namespace rejects those pods is read from the PSS
  definition, not from an admission controller.
- **`external-secrets.io/v1beta1`** (`secret.yaml:23`) is what the chart emits. Whether the ESO
  version on the reference cluster still serves that apiVersion is unchecked — worth confirming
  before the first install rather than after.
- **Ingress reconciliation without a class**: that an Ingress naming no class is served only where a
  default IngressClass exists is standard behaviour, not tested here.
- **`ImagePullBackOff`, `CreateContainerConfigError`, `FailedGetPodsMetric`** and every other
  cluster-side symptom named above: the rendered manifest and the missing prerequisite are verified;
  the symptom is the documented Kubernetes behaviour, not something observed on a cluster.
- Anything about `acpctl install`, `uninstall`, `support-bundle`, `packaging/acceptance/**` or
  `packaging/docs/lifecycle.md`: in flight in #1796, deliberately not read and not assessed.
