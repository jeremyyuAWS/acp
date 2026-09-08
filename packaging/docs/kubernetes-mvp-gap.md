# Kubernetes MVP — what is missing before the first acceptance run

A decision document, not a status summary. Every claim below names the file and line, or the
command and its output, that produced it. Where something could not be run, it says so and the
finding is marked unverified rather than asserted.

## Nothing moves from `planned` to `supported` in this change

`presets.SUPPORT_STATUS` (`packaging/cli/acpctl/presets.py:68-75`) marks every Kubernetes target
`planned`, and its own definition of the word is *"a reference deployment in THIS repository runs
the contract suite against it"*. No cluster is reachable from these sessions:

```
$ command -v kubectl ; echo "exit=$?"
exit=1
$ python -m acpctl doctor packaging/examples/standard-production.acp-deployment.yaml -n acp ; echo "exit=$?"
  [????] cluster.reachable: kubectl is not on PATH. …
NOTHING WAS CHECKED — the cluster could not be reached. This is not a pass.
exit=2
```

PRD §7 requires the packages to "document which combinations are production-supported versus
preview", and §20.3 makes a support claim mean the reference deployment passed the smoke suite.
A rendered chart is not that evidence. Anything in this change that reads as progress toward
`supported` is progress toward being *able to run* the acceptance evidence, not the evidence.

**What the first acceptance run needs, and this is the ask.** None of it exists here:

| Needed | Why the run cannot substitute for it | Rough shape |
|---|---|---|
| A disposable Kubernetes cluster, admin on it | KEDA, an ingress controller, a CNI that enforces NetworkPolicy and PodSecurity admission are all cluster-level, and three of them fail silently (see the prerequisites table) | 3+ nodes; kind/k3d covers the render and admission checks but not zone spreading or a real LoadBalancer |
| External Postgres | The chart refuses to render against in-cluster data services (`_dataservices.tpl:33-51`); `standard-production` needs `max_connections ≥ 418` (ADR 0048 amendment, `packaging/docs/service-inventory.md`) | one instance, reachable from the cluster |
| External Redis and S3-compatible object storage | Same refusal; and the remediated-copy store is the PRD §20.5 acceptance criterion | one each |
| A registry the cluster can pull from, holding images built from this repo | The chart pulls repositories nothing here builds — gap A1 | any OCI registry + pull secret |
| A throwaway DNS name and TLS secret, or an ingress controller with a default class | Rendered Ingress names no class and a TLS secret nothing creates — see the Ingress row below | one hostname |

Cost and blast radius are the reason this is an ask rather than a task: it is a billable
environment, and nothing in this tree provisions anything by design (`packaging/README.md:9-14`),
so standing one up is the owner's decision rather than a step in this change.

## How the chart findings were produced

helm **is** available here, so chart claims below are observations of rendered output, not
readings of template text.

```
$ helm version --short
v3.16.3+gcfd0749
$ export PYTHONPATH=packaging/cli
$ python -m acpctl values packaging/examples/<profile>.acp-deployment.yaml > values.yaml
$ helm template acp packaging/chart/acp -f values.yaml
```

| Example | `helm template` | Note |
|---|---|---|
| `standard-production` | exit 0, 22 objects | platform `azure`, ESO path |
| `high-availability` | exit 0, 24 objects | adds a PDB and a third `ScaledObject` |
| `regulated` | **exit 1** | `postgresql/redis/objectStorage (mode: self-hosted)` refused; renders with the documented `--set …external=true` escape (ADR 0048 addendum), then exit 0 |
| `evaluation` | **exit 1** | `mode: embedded`; Compose-only by contract, so this is correct behaviour, not a defect |
| `acpctl init --platform kubernetes --profile standard` | exit 0, 22 objects | the customer-cluster MVP path; **renders no Secret and no ExternalSecret** |

`pytest tests/test_packaging_chart.py -q` → **42 passed, 1 skipped** (the skip is
`test_ci_has_helm`, which is CI-only by design, `tests/test_packaging_chart.py:85`).

Not checkable here, and not claimed anywhere below: admission behaviour, KEDA/ESO reconciliation,
NetworkPolicy enforcement, image pulls, scheduling, and anything `acpctl doctor`/`status` reads.


## What the chart RENDERS versus what the cluster must already provide

`packaging/README.md:57-61` carries three rows. All three are still true. The chart renders more
than they admit, and the table below is what a `standard-production` and a customer-Kubernetes
render actually contain. **Silent** means Kubernetes accepts the object and nothing reports that
it does nothing.

| Rendered object | Cluster must provide | If absent | Loud? | Checked by `doctor`? |
|---|---|---|---|---|
| `ScaledObject` ×2–3, `TriggerAuthentication` | KEDA (CRDs **and** a running controller) | CRDs missing: apply fails. CRDs present, controller not: workers sit at their floor and the queue grows | mixed | yes (`doctor.py:191`) |
| `NetworkPolicy` ×4 (`default-deny`, `api`, `worker-no-ingress`, `egress`) | a CNI that enforces them | pod networking stays fully open | **no** | inferred only (`doctor.py:217`) |
| `ExternalSecret` (ESO backends only) | External Secrets Operator + a `SecretStore` | pods stay in `CreateContainerConfigError` | yes | yes (`doctor.py:256`) |
| **nothing** — when `secrets.provider: kubernetes` | a pre-created Secret `<release>-secrets` carrying every `secrets.refs` key | same `CreateContainerConfigError` | yes | **no** — `check_external_secrets` returns `[]` when ESO is off (`doctor.py:257-260`) |
| `HorizontalPodAutoscaler` with a `Resource: cpu` metric | metrics-server | `FailedGetResourceMetric`, no API scaling | quiet | yes (`doctor.py:339`) |
| …and a `Pods: acp_concurrent_requests` metric | a custom-metrics adapter **and an application that exports it** | `FailedGetPodsMetric`; see gap C2 | quiet | partially |
| `Ingress`, no `ingressClassName`, `secretName: acp-tls` | a **default** IngressClass, and something that creates `acp-tls` | no class default: never reconciled. no secret: controller serves its own cert | **no** | class existence only (`doctor.py:317`) |
| every workload image | a registry holding `acp`, `acp-worker`, `acp-ollama-gateway`, `acp-grafana` at the release tag, pullable without a pull secret (`image.pullSecrets` is never emitted) | `ImagePullBackOff` | yes | no |
| every pod, no `seccompProfile` | a namespace **not** enforcing PodSecurity `restricted` | pods rejected at admission | yes | no |
| `ai.ollama.gpu: true` | nothing — see gap B9 | the model runtime schedules onto a CPU node and no object says otherwise | **no** | no |

Row 1's qualification matters and the README's version does not carry it: "no error" holds only
when the KEDA **CRDs** are installed and the controller is not. With no CRDs at all, the API
server rejects `keda.sh/v1alpha1` and `helm install` fails at apply. *Unverified — no cluster;
reasoned from the API-server contract, not observed.*

Row 4 is the customer-Kubernetes default. `acpctl init --platform kubernetes` writes
`secrets.provider: kubernetes` (line 141 of its output), `secret.yaml:22` renders an
`ExternalSecret` only for ESO backends, and the resulting manifest set contains no `Secret` of any
kind — verified by rendering it. So the one prerequisite the operator will hit first on the MVP
path is the one `doctor` does not ask about.


---

## A — Release artifacts and supply chain

**Owned elsewhere.** Workstream A belongs to the session on
`claude/acp-portable-packaging-l3krqe`. This section states the gap as the Kubernetes MVP hits it
and deliberately proposes no implementation.

**Exists.** Three images are built from this tree, all by `az acr build` from the Azure deploy
scripts: the application image (`deploy/public/deploy.sh:264`, from `deploy/public/Dockerfile`),
the first-party Grafana (`deploy.sh:644`) and the Ollama gateway
(`deploy/ollama/gpu-runbook.sh:45`). Each is tagged with a CalVer `TAG`.

**Missing for the acceptance run.**

**A1 — the chart pulls images nothing in this repository builds.** This is the first thing an
acceptance run hits and it stops it dead.

| | api / migrate / preflight | worker ×3 | ollama | grafana |
|---|---|---|---|---|
| `helm template` pulls | `acp:2026.9` | `acp-worker:2026.9` | `acp-ollama-gateway:2026.9` | `acp-grafana:2026.9` |
| `acpctl plan` names | `acp-web-api`, `acp-migrations`, `acp-preflight` | `acp-discovery-worker`, `acp-assess-worker`, `acp-remediate-worker` | `acp-ollama-gateway` | `acp-grafana` |
| this repo builds | `acp-app:${TAG}` (`deploy/public/deploy.sh:36`) | — | `acp-ollama:${TAG}` (`deploy/ollama/gpu-runbook.sh:45`) | `acp-grafana:${TAG}` (`deploy.sh:644`) |

Three naming systems, and the intersection with what is built is `acp-grafana` alone. The chart's
names come from `values.yaml:23,25` — `acpctl values` overrides only `ollamaRepository` and
`grafanaRepository` (`values.py:131-132`), so `repository`/`workerRepository` fall through to the
chart defaults. Verified: grepping `deploy/ .github/ azure-pipelines.yml` for the eight PRD §5.1
artifact names returns **0 hits, exit 1**, while the same grep for `acp-grafana` returns 2 files.

The worker half has a second edge. `worker-deployment.yaml:56-67` sets no `command`, so it relies
on `acp-worker` being an image whose entrypoint is the worker. Today the worker tier is the *same*
image started differently — `az containerapp … --command acp-worker` (`deploy/public/deploy.sh:585`),
a launcher baked in as `/usr/local/bin/acp-worker` — while `deploy/public/Dockerfile`'s `CMD` is
uvicorn. So pointing `workerRepository` at the existing image without also setting `command` gives
three worker Deployments running the API.

*Smallest next dependency:* decide whether the MVP builds two image names or seven (PRD §5.1 wants
seven, separately signed), then make one build produce them. Until an image exists, every later
step in B, C and D is untestable.

**A2 — the rest of PRD §5.1 has no artifact to attach to.** Once an image exists, §5.1 asks for
eight more properties of it, and none is produced anywhere in this tree today: one source revision
and one ACP CalVer stamped per image; a published immutable digest per image; an SBOM;
vulnerability scanning; a cryptographic signature; **verification of that signature before
install**; and AMD64/ARM64 support recorded *per analysis engine* rather than claimed for the
release. Two of these are already visible from the Kubernetes side as behaviour rather than as
policy:

- `acpctl values` emits `image.digests: {}` (`values.py:136`) and stamps every file it renders
  with *"Image digests are UNRESOLVED here"* (`values.py:270`). The chart honours a digest over a
  tag whenever one is supplied (`_helpers.tpl:49-52,75-80`), so the mechanism exists and the input
  does not. PRD §5.1 requires templates to reference digests, not mutable tags; every render
  produced for this report referenced a tag.
- `image.pullSecrets` is never emitted by `acpctl values`, so `imagePullSecrets` appears in no
  rendered manifest — verified: `grep -n imagePullSecrets` over both renders returns **0 hits,
  exit 1**, against a control of 8 `serviceAccountName` hits in the same file. A private registry
  is the normal case for a customer cluster.

Signature verification before install is the one with an ordering consequence for workstream D:
it has to happen in the install path, so it cannot be retrofitted after that path is written
without changing it.

---

## B — Helm production hardening

The workstream-B hardening checklist, run against the **rendered** output of
`standard-production` and `high-availability` rather than against template text. The requirements
are the Kubernetes half of PRD §5.2 plus §8 (profiles), §12 (storage) and §13 (security).

| # | Requirement | State | Evidence |
|---|---|---|---|
| 1 | Restricted pod security | **partial** | `runAsNonRoot`, `runAsUser`, `fsGroup` (`values.yaml:170-173`); `allowPrivilegeEscalation: false`, `drop: [ALL]` (`values.yaml:174-178`). `grep seccompProfile <rendered>` → **exit 1, 0 hits**, and `restricted` requires one. `readOnlyRootFilesystem: false` on every container including the API and workers (`values.yaml:176`; rendered lines 253, 397, 459, 527) |
| 2 | Requests **and** limits | **partial** | api, all workers, migrate, preflight: both, from the preset (`values.py:68-79`; `migration-job.yaml:66-72`). **ollama and grafana render with no `resources` at all** — `acpctl values` emits none (`values.py:180-190`), the templates are `with`-guarded. Both are then BestEffort and first to be evicted; on a namespace with a LimitRange requiring requests they are rejected |
| 3 | Temporary storage | **partial** | `ephemeral-storage` request and limit on every ACP tier from `presets.PRESETS` (`values.py:72,77`), and the floor is computed and enforced (`presets.minimum_ephemeral_gib`). But `presets.py:115-122` says the ×4/×1/×1.5 factors are "DECLARED PLANNING CONSTANTS, NOT MEASUREMENTS", and nothing renders an `emptyDir` with a `sizeLimit` — scratch lands on the node's writable layer |
| 4 | Topology spreading | **weak** | `grep topologySpreadConstraints` → **exit 1**. One `affinity` block in the whole HA render (line 355): the API's *preferred* anti-affinity, `topologyKey: kubernetes.io/hostname` (`api-deployment.yaml:82-91`), and only when `replicaCount > 1`. Worker tiers running 2–4 replicas in the HA profile get nothing, so all four remediate pods may share one node. PRD §8 asks HA for *multi-zone*; hostname is not zone |
| 5 | Disruption protection | **partial** | `podDisruptionBudget.enabled` is true only for `high-availability` (`values.py:163`) — so a `standard` API tier running 2–4 replicas has no PDB and a node drain can take both. PDB is API-only, argued in `pdb.yaml:11-14`. `minAvailable` is hardcoded 1 (`values.py:164`), so a 3-replica HA API may be drained to 1 |
| 6 | Service accounts | **weak** | One SA for api, workers, ollama, grafana and both hook Jobs (`serviceaccount.yaml`). No `automountServiceAccountToken: false` anywhere (`grep` → **exit 1**), no Role/RoleBinding rendered, no annotations (gap D1). Nothing here needs the API server, so the token is mounted for no reason |
| 7 | Probes | **satisfied, with one hole** | API gets `/readyz` readiness and `/healthz` liveness, deliberately different endpoints (`_helpers.tpl:192-208`). Workers get none, argued (`worker-deployment.yaml:68-74`). ollama gets startup+readiness, grafana readiness — **neither gets a liveness probe**, so a wedged model runtime is never restarted |
| 8 | Graceful worker shutdown | **satisfied on both sides, untested** | `terminationGracePeriodSeconds: 300` (`worker-deployment.yaml:55`); the process half is real — `api/worker_main.py:31-38,55-57` installs SIGTERM/SIGINT handlers and drains. Untestable here: no image, no cluster |
| 9 | GPU only where required | **NOT rendered** | `standard-production` sets `ai.ollama.gpu: true`; `grep nvidia <rendered>` → **exit 1, 0 hits**. `ollama.yaml:108-113` carries a comment explaining why "only the limit is set" for `nvidia.com/gpu` — **no line in the template sets it**, and the `if .Values.ai.ollama.gpu` block guards only `nodeSelector` and `tolerations`, which `acpctl values` never emits (`values.py:180-184`). So `gpu: true` renders nothing whatsoever, the pod schedules on a CPU node, and the vision lane silently runs on CPU |
| 10 | No public ingress on any worker | **satisfied** | Rendered Services are `acp-api`, `acp-ollama`, `acp-grafana` only — no worker Service exists. `Ingress` backend is `acp-api` (rendered line 900). `acp-worker-no-ingress` NetworkPolicy with `ingress: []` renders in all three profiles. ollama and grafana are ClusterIP with tests pinning it |
| 11 | No authoritative output on ephemeral storage only | **NOT satisfied** | See B-headline below |

**B-headline — the object-storage seam does not meet, and it fails silently.**
`_helpers.tpl:175-181` projects each `secrets.refs` key as an uppercased env var, so
`object-storage` arrives in every container as `OBJECT_STORAGE` (rendered lines 305, 573, 690
and 807 — the API and all three worker tiers).

```
$ grep -rn OBJECT_STORAGE api/ engine/ deploy/ realtime_gateway/ hub/ ; echo exit=$?
exit=1                                    # 0 hits
$ grep -rln ACP_BLOB_ACCOUNT api/ engine/ deploy/ ; echo exit=$?
api/blob.py
deploy/public/deploy.sh
exit=0                                    # the control: the search works
$ grep -c ACP_BLOB <rendered> ; echo exit=$?
0
exit=1
```

`api/blob.py:19,26` reads `ACP_BLOB_ACCOUNT` and sets `_ENABLED = bool(_ACCOUNT)`; with it unset
"a no-op (returns None everywhere)" by the module's own docstring. `blob.py` is the **primary**
store for a remediated file (ADR 0010) — Drive write-back is a best-effort mirror. So a
Helm-installed ACP writes remediated output to no durable store and reports nothing: PRD §12 and
acceptance criterion §20.5 fail, quietly, and `acpctl plan` says the opposite in its own output
("object-storage … Authoritative output lives here").

This is the same class of defect the chart already fixed once for telemetry
(`test_the_workloads_get_the_telemetry_credential_the_application_reads`), and nothing generalises
that test: `grep "ACP_BLOB\|blob" tests/test_packaging_chart.py` → **exit 1, 0 hits**.

*Smallest next dependency for B:* one test that asserts every projected secret-ref env name is a
name the application actually reads. It closes the blob gap and prevents the next one; every other
row here is a chart edit that can follow it.

---

## C — Portable acceptance suite

**Exists.** 11 packaging test files, 215 test functions, run in CI. They assert on *rendered
manifests* rather than template text (`README.md:228-235`), pin the KEDA queue lanes against
`api/core.py`'s own tuples, and refuse to let a values knob exist unread
(`test_no_other_values_knob_is_silently_ignored`). `packaging/acceptance/**` is **being written in
this same change** and is not assessed here.

**Missing for a Kubernetes MVP acceptance run.**

**C1 — no test in this repository stands up anything.** `grep -rln "docker compose"` over `tests/`
returns three files; all three read the compose YAML as text
(`tests/test_bench_harness.py:14`, `tests/test_monitor.py:440`,
`tests/test_packaging_chart.py:1018`). Nothing starts a container, a stack or a cluster. PRD §19
wants contract tests that assert API readiness, worker registration, queue processing,
remediation, artifact persistence, SSE delivery, backup, upgrade and rollback against every
target; today's suite covers the *render*, which is one precondition of the first of those.

**C2 — the API tier's declared autoscaling signal cannot exist.** The rendered HPA carries a
`Pods` metric named `acp_concurrent_requests`. That string appears exactly twice in the repo — the
template that emits it (`autoscaling.yaml:54`) and `doctor.py:369`'s advice to install an adapter
that publishes it. There is no `prometheus_client` import and no `/metrics` route in `api/`
(`grep -rn "prometheus_client\|'/metrics'" api/` → **exit 1, 0 hits**; control `grep -rln readyz
api/` → 15 files). No adapter can publish a metric the application does not expose, so the API
tier degrades to scaling on CPU alone — which PRD §11 permits only as a *secondary* signal.

**C3 — the plan promises a service the chart never installs.** `acpctl plan` on
`standard-production` lists `acp-langfuse` under "resources this plan would create"; the render
contains no langfuse workload. This one is known and pinned
(`tests/test_packaging_chart.py:636-645` — the chart *does* project `langfuse-secret-key` into the
API, so the application is configured to talk to a Langfuse the release does not deploy) and it is
a contract decision, not an omission to fill. It needs deciding before an acceptance run scores it.

*Smallest next dependency for C:* one target, one cluster, one end-to-end assertion — API becomes
ready, a worker claims a job, a remediated artifact lands in object storage and is readable after
the pod is deleted. That last clause is the only thing that tests B11.

---

## D — `acpctl` lifecycle

**Exists.** `validate`, `plan`, `inventory`, `values`, `init`, `doctor`, `status` (README:66-78);
all read-only, with `doctor`/`status` restricted to a `kubectl` verb allow-list. `helm template`
of a real `acpctl values` output is asserted in CI by 42 tests. The lifecycle commands
(`install`, `uninstall` and their state handling) are **being written in this same change** and
are not assessed here.

**Missing for the acceptance run.**

**D1 — `secrets.workloadIdentity` is accepted by the validator and rendered by nothing.**
`spec.py:_rule_required_secrets` treats a name under `workloadIdentity` as satisfying a required
reference, deliberately, because production reaches Blob through a managed identity and holds no
storage credential (`schema/acp-deployment.schema.json:507-514`). The derived production document
uses it (`packaging/docs/azure-current.acp-deployment.yaml:86-87`). But `grep -rn workloadIdentity
packaging/chart/acp/ packaging/cli/acpctl/values.py` → **exit 1, 0 hits**, and the rendered
ServiceAccount carries no annotations at all. `serviceaccount.yaml:9-16` calls itself "the ONE
place the platform reaches into the workloads"; `acpctl values` emits no `serviceAccount` key, so
that place is always empty. A document that validates on the strength of workload identity
installs a release with neither a credential nor an identity.

*Smallest next dependency:* `acpctl values` must emit `serviceAccount.annotations` from the
adapter, and a test must fail when a `workloadIdentity` entry produces no annotation.

**D2 — nothing in the lifecycle path can be exercised here.** `doctor` and `status` both
exit 2 with *"NOTHING WAS CHECKED"* without a cluster (run at the top of this report), and the
install path has no image to pull (workstream A). So the lifecycle work landing in this change is
reviewable as code and not yet as behaviour — which is the same sentence as workstream C's, and
for the same missing pieces.

---

## Support status, and what would justify changing it

**Exists.** The status table is machine-readable and deliberately pessimistic
(`presets.py:60-75`), the chart's `NOTES.txt:3-8` prints a `PLATFORM STATUS: PLANNED` banner on
every non-supported install, and `acpctl validate` warns on it (observed in the run above).

**Missing.**

**1 — `compose: supported` is itself unevidenced by the definition beside it.** The comment
defines `supported` as "a reference deployment in THIS repository runs the contract suite against
it"; per C1 no suite runs against anything. Compose is the working, shipped path and the claim is
probably *true*; it is not *evidenced*, and it is the row a reader will point at when asking why
Kubernetes cannot have the same word.

**2 — the observability requirement has no implementation off Azure.** `acpctl validate` on a
`kubernetes` document warns: *"'local' has no implementation in this application —
api/telemetry.py configures the Azure Monitor distribution only, so telemetry will be declared and
off"*. Confirmed in `api/telemetry.py` (Azure Monitor distro, `configure_azure_monitor`, no OTLP
exporter anywhere). PRD §14 requires regulated installations to support fully local collection.
A customer-Kubernetes install therefore collects nothing, by design, today.

**3 — no backup, restore or DR surface exists in the contract.** `grep -n "rto\|rpo\|restoreTest"
packaging/schema/acp-deployment.schema.json` → **exit 1**; the only backup field is
`backupRetentionDays` (schema:296). PRD §8 makes RTO/RPO a defining property of the HA profile and
§16 says a backup is not healthy until a restore test has succeeded. Neither is expressible, so
neither is checkable, and `high-availability` currently means replica counts plus HA data services.

*Smallest next dependency:* pick the one target that will be certified first (below), and
write down what evidence its certification requires. Everything else here is scoped by that choice.

## Progress table (PRD §9 shape)

`verified` is used for nothing: no target has acceptance evidence, so nothing has met the bar the
word describes.

| Workstream | State | Evidence | Blocker | Next action |
|---|---|---|---|---|
| Release artifacts | not started | The chart pulls `acp` / `acp-worker`; the repo builds `acp-app` / `acp-grafana` / `acp-ollama`; `acpctl plan` names a third set. 0-hit grep with a passing control (A1). No digests, SBOMs, provenance, scanning or signing anywhere (A2) | Owned by the session on `claude/acp-portable-packaging-l3krqe` | Decide two image names or seven, then build them under the names the chart pulls |
| Helm hardening | in progress | Checklist above against rendered output: 3 satisfied, 5 partial, 2 not rendered, 1 not satisfied | B11 (object storage) is a correctness bug, not a posture gap | Add the projected-env-name test; then `seccompProfile`, ollama/grafana resources, worker spreading |
| Acceptance suite | in progress | `packaging/acceptance/**` is **in flight in this same change** and is not assessed here. Today: 215 packaging tests, none of which start a container, stack or cluster (C1) | No cluster; no image to install | One disposable cluster, one end-to-end assertion including artifact persistence after a pod delete |
| Lifecycle | in progress | `install`/`uninstall` and their state handling are **in flight in this same change** and are not assessed here. Read-only commands ship today (`packaging/README.md:66-78`); `workloadIdentity` renders nothing (D1) | No image, no cluster: `doctor`/`status` exit 2 here | Emit `serviceAccount.annotations`; then exercise install against the first real cluster |
| AKS | not started | `SUPPORT_STATUS["azure"] = "planned"` (`presets.py:68-75`). `deploy/public/` deploys Container Apps, a different topology (ADR 0048) | Everything above, plus a billable environment | Run the acceptance suite against AKS once one exists; do not rename the status before that |
| On-premises | not started | `SUPPORT_STATUS["onprem"] = "planned"`; `onprem` is `self-hosted`-only (`presets.py:78-88`), which is the mode the chart refuses to render without an override | Which distribution gets certified first is a customer decision (see stop-and-ask) | Pick the distribution, then treat it as a second acceptance target |

## Stop-and-ask conditions this work touches

These are human decisions. Each is left open deliberately; none is blocked on engineering.

| Condition | Why it is a decision | State |
|---|---|---|
| Which on-premises Kubernetes distribution is certified first | PRD §4 excludes "arbitrary Kubernetes distributions without passing certification tests", so the first one is a commitment to a customer's cluster shape — it needs a customer signal, not a preference | **outstanding** |
| Provisioning a billable cloud environment for the acceptance run | Cost and blast radius; see the ask at the top | **outstanding** |
| RTO, RPO and backup retention | PRD §8/§16 make these customer-defined; the schema cannot invent them (support-status item 3) | **outstanding** |
| What `self-hosted` means — operator-provisioned or chart-provisioned data services | ADR 0048's addendum raises it and explicitly does not decide it; today it means the `regulated` example does not render without an override | **outstanding** |
| Whether `acp-langfuse` belongs in the contract at all | Compose runs it, production has never had it (C3); which side moves is a product decision | **outstanding** |
| Whether worker tiers get PDBs | `pdb.yaml:11-14` argues API-only because a drain that cannot complete is its own incident. Defensible; it is a policy choice an HA customer may disagree with | decided, revisit with a customer |
| Hostname egress enforcement | `networkpolicy.yaml:74-87`: NetworkPolicy matches IPs, not names. A real allow-list needs Cilium `toFQDNs` or an egress proxy — a cluster requirement to impose on a customer | **outstanding** |
| Measuring the storage expansion factors | `presets.py:115-122` states ×4/×1/×1.5 are unmeasured. Measuring changes every plan's floor | **outstanding** |

## What is asserted here without having been run

Kept short on purpose; everything else above is an observed command or a cited line.

- **KEDA/ESO CRD-absent behaviour** (prerequisites table, rows 1 and 3): that a missing CRD fails
  the apply while a missing *controller* fails silently is reasoned from the API-server contract,
  not observed. No cluster.
- **PodSecurity `restricted` rejection**: the absence of `seccompProfile` is verified in the
  rendered output; that a `restricted`-enforcing namespace rejects those pods is read from the PSS
  definition, not from an admission controller.
- **`external-secrets.io/v1beta1`** (`secret.yaml:23`) is what the chart emits. Whether the ESO
  version on the reference cluster still serves that apiVersion is unchecked — worth confirming
  before the first install rather than after.
- **Ingress reconciliation without a class**: that an Ingress naming no class is served only where
  a default IngressClass exists is standard behaviour, not something tested here.
- Anything about `acpctl install`, `uninstall`, `packaging/acceptance/**` or
  `packaging/docs/lifecycle.md`: in flight in this same change, deliberately not read and not
  assessed.
