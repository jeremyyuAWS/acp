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
`PUT /rubric` writes `<repo>/config/rubric.active.json` INTO THE IMAGE
(`api/routes/rubric.py:63`), so a read-only root turns an owner-only admin endpoint into a 500.
Masking `/app/config` with an `emptyDir` is not a way round it — that hides `rubric.default.json`
and `rule-catalog.json`. Moving the write to the database or to `$TMPDIR` is an application change,
not a packaging one, so the default stays `false` and
`test_the_shared_root_filesystem_is_writable_and_that_is_deliberate` pins both halves: the value,
and the write it exists for.

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

**What is missing.** No `topologySpreadConstraints` anywhere in the chart. No PersistentVolumeClaim
and no volumes at all —
worker scratch is the node's ephemeral storage, bounded only by the limit above. The PDB renders
only for the `high-availability` profile and only for the API tier
(`values.py`: `"enabled": rt["profile"] == "high-availability"`; `templates/pdb.yaml`), which is a
recorded decision but means a standard-production install has no disruption budget on any tier. No
backup or restore Job, which PRD S5.2 lists as part of the Kubernetes package. Langfuse is deployed
ungated by Compose and rendered by nothing in the chart — asserted, deliberately, by
`test_packaging_chart.py::test_compose_deploys_what_the_chart_omits`.

**The blocking gap: there is no reference Kubernetes version, and no cluster to render against.**
The only version fact in the repository is `doctor.MINIMUM_KUBERNETES = (1, 23)`
(`packaging/cli/acpctl/doctor.py:41`), a floor derived from when `policy/v1` and `autoscaling/v2`
went stable — not a version anything has been validated on. `grep -rln "kind create cluster\|k3d\|minikube" tests/ packaging/` matches this
report and nothing else; CI installs helm (`.github/workflows/ci.yml:211`) solely so
`helm template` and `helm lint` can run. Every row above is therefore a claim about text, and #1798 is the proof that
text can be consistently wrong.

**Next step.** One test asserting that every projected secret-ref env name is a name the
application actually reads — it closes B11 and prevents the next one. Then name a reference
Kubernetes version and stand up a disposable cluster in CI; until one exists, hardening work cannot
be distinguished from hardening-shaped YAML.

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

Ordered, smallest first dependency at the top.

1. **Something must build the artifacts a release manifest names.** `deploy/public/deploy.sh`
   builds `acp-app` and `acp-grafana` for Container Apps; nothing builds
   `acp-ollama-gateway`. Until an image exists there is nothing to pin, sign or pull.
2. **A registry the acceptance run can pull from**, and a tag/digest convention for it. The
   example's `runtime.imageRegistry` is a production ACR; an acceptance run needs a target a CI job
   can push to and a throwaway cluster can read.
3. **A real `ACPRelease` emitted by that build**, with signatures and SBOMs that exist rather than
   are declared. The contract and its checks are in place (§A); the producer is not.
4. **A disposable cluster in CI.** No `kind`, `k3d` or `minikube` reference exists outside this
   report; `helm` is installed only to render.
5. **The acceptance report format and runner** — in flight in #1796. Without it, ten passing
   scenarios produce ten passing scenarios and no artifact anybody can compare across runs.
6. **`acpctl install` exercised against a cluster** — in flight in #1796, never run against a real
   one. Everything from scenario 3 onward (queue processing, restart mid-job, scale-down, upgrade,
   restore) presupposes it.
7. **Signature verification at install time**, which is the point at which the run stops being a
   smoke test and starts being evidence about a specific release.

Items 1-3 are prerequisites for a manual `helm install`. Items 4-7 are what turn that into a
repeatable acceptance run.

---

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

## Progress (PRD §9 shape)

`verified` is used for **nothing**: no target has acceptance evidence, so nothing has met the bar
the word describes.

| Target | State | Evidence | Blocker | Next action |
|---|---|---|---|---|
| Release artifacts | in progress | `ACPRelease`, `acpctl release verify`, `--release` on `values`/`plan` (#1797; `tests/test_packaging_release.py`, 37 cases) — a manifest reconciles the plan's eight names, the chart's four components and the built artifacts, and renders every image by digest | Nothing builds, signs, SBOMs or scans an artifact, so no real manifest exists and CI has no release to fail on. Scanning and provenance are not even expressible in the schema | Build the images in CI and emit a signed manifest from that build |
| Helm hardening | in progress | Requests/limits with `ephemeral-storage` on every workload; restricted pod security **enforced by the API server on the disposable cluster**, not merely rendered (#1808); `terminationGracePeriodSeconds: 300` with a matching drain window (#1805); no worker Service; `doctor` blocks on KEDA, CNI and ESO. Two silent defects closed by #1798 | `kindest/node:v1.31.4` is a version the chart RUNS on, not one anything is supported on — naming a supported distribution is PRD §4 and an owner decision. No topology spread; no `readOnlyRootFilesystem` (blocked on `PUT /rubric` writing into the image); no backup/restore Job | Topology spread, then a backup/restore Job |
| Acceptance suite | in progress | `packaging/acceptance/**` **in flight in #1796**, not assessed here: ten scenarios, a validated report schema, and a self-test that runs with no cluster. The disposable kind cluster (#1799) now exists and installs the chart | The suite has never been run against it, so every scenario result is synthetic — and a synthetic run is forced ineligible by construction | Run the suite against the kind cluster and keep the first real report |
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
