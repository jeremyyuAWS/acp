# Kubernetes MVP: what exists, what is missing, what blocks the next step

## What this is

The Kubernetes MVP is the milestone at which one ACP release can be installed onto a throwaway
cluster by `acpctl`, exercised by an automated acceptance suite, and upgraded, rolled back and
restored — with every artifact it runs identified by an immutable digest. This report maps the
repository against the four workstreams an implementation PRD defines (A release artifacts, B Helm
hardening, C acceptance suite, D `acpctl` lifecycle) and says, for each, what is blocking rather
than what is merely absent.

No disposable-cluster acceptance run is possible today for one reason that sits underneath all
four: **the eight release images PRD S5.1 names do not exist.** Nothing in this repository builds
them, the chart does not reference them, and `acpctl install` — the command that would resolve
their digests — exits 2. Everything below is downstream of that.

Nothing in this report is verified in the acceptance sense. Rendered YAML and green unit tests are
evidence that a template produces the text it was written to produce; they are not evidence that
anything runs.

---

## A. Release artifacts and supply chain

**What exists.** `packaging/cli/acpctl/inventory.py:61-75` is the one place the release artifacts
are named: `acp-web-api`, `acp-discovery-worker`, `acp-assess-worker`, `acp-remediate-worker`,
`acp-ollama-gateway`, `acp-grafana`, `acp-migrations`, `acp-preflight` — eight, matching PRD S5.1.
`acpctl plan` prints all eight with their tag and `digest  <unresolved>`, and
`tests/test_packaging_cli.py::test_plan_does_not_present_an_unresolved_tag_as_a_pin` keeps that
honest. The chart is ready to consume digests: `acp.image`
(`packaging/chart/acp/templates/_helpers.tpl:56-81`) prefers `image.digests.<component>` over the
tag and does not append the tag when a digest is present.

**What is missing.** Everything that would produce an artifact. Repository-wide there is no
`cosign`, `syft`, `grype`, `sigstore`, `in-toto`, SPDX or CycloneDX reference in any workflow,
script or Python file — so no signing, no SBOM, no provenance and no scanning gate. Nothing
committed on this branch is a release manifest, machine-readable or otherwise, so nothing could
fail CI on a mixed-revision or unsigned release. ARM64 is not recorded anywhere, per analysis
engine or otherwise.

**One part of this lands with this report**, and the rest of section A is written against the
repository as it stood before it. The release-manifest contract — `ACPRelease`
(`packaging/schema/acp-release.schema.json`), its rules (`packaging/cli/acpctl/release.py`),
`acpctl release verify`, and `--release` on `values` and `plan` — is in the same change as this
file, and closes the first half of workstream A's acceptance criterion: a machine-readable manifest
maps every component to a digest, source revision, SBOM and signature, and Helm consumes the
digests. What it does NOT close is the other half: nothing builds the artifacts, nothing signs
them, and CI has no release to fail on. The manifest is the interface those need to produce, which
is why it went first.

**What is actually built today.** `deploy/public/deploy.sh:36` sets `IMAGE="acp-app:${TAG}"` and
`:264` builds it with `az acr build` from `deploy/public/Dockerfile`; that single image is then set
on both the worker app (`:584`) and the API app (`:614`). `:635,644` build `acp-grafana:${TAG}` from
`deploy/grafana/Dockerfile`. `deploy/ollama/gpu-runbook.sh:45` builds `acp-ollama:${TAG}` from
`Dockerfile.gpu`; nothing in the repository builds the CPU `deploy/ollama/Dockerfile`. So one of the
eight names is built — `acp-grafana` — and the other seven are not built by anything.

**The blocking gap: the plan and the chart disagree about which artifacts an install runs, and
neither set is built.** `helm template` of `packaging/examples/standard-production.acp-deployment.yaml`
renders exactly four image references — `<registry>/acp`, `<registry>/acp-worker`,
`<registry>/acp-ollama-gateway`, `<registry>/acp-grafana` — against the plan's eight. Only two names
overlap. The disagreement has a specific cause: `values.py` emits `ollamaRepository` and
`grafanaRepository` from `inventory.IMAGES` but emits no `repository` or `workerRepository` at all,
so those two fall through to the chart defaults `acp` and `acp-worker`
(`packaging/chart/acp/values.yaml:22-30`) — names taken from neither the inventory nor `deploy.sh`,
which builds `acp-app`. The three worker tiers share one `workerRepository`, so the separately
scannable, separately signable per-lane worker images the PRD asks for cannot be expressed by the
chart even if they existed; `acp.image` has four component keys (`api`, `worker`, `ollama`,
`grafana`), so a resolved digest map would have four entries, not eight.

`acp-migrations` and `acp-preflight` are worse than unbuilt: they are not chart components.
`migration-job.yaml:53` and `preflight-job.yaml:44` both render
`include "acp.image" (dict "root" $ "component" "api")` — the hooks run the API image. The two Jobs
the inventory presents as separate artifacts have no separate artifact behind them.

**Next step.** Decide the artifact set once — either the chart grows the eight components and the
build produces them, or `inventory.IMAGES` is cut to what is actually shipped — and make one test
assert that the plan's image list and the chart's rendered image list are the same set. Until they
agree, "sign the release images" has no unambiguous subject.

---

## B. Helm production hardening

**What exists**, and more of it than the workstream name suggests. The chart renders API and worker
Deployments, migration and preflight Jobs, Service, Ingress, ServiceAccount, NetworkPolicy, PDB,
Grafana, Ollama and KEDA `ScaledObject`s. Concretely, from the standard-production render:

- **Requests and limits on every workload, including `ephemeral-storage`** — the API tier at
  `cpu 1 / memory 2Gi / ephemeral-storage 4Gi`, assess and remediate at `2 / 4Gi / 8Gi`, from
  `presets.PRESETS` via `values.py:72,77`. `tests/test_packaging_validate.py::
  test_ephemeral_storage_below_the_computed_floor_is_rejected` makes the storage floor fire.
- **Pod security** — `podSecurityContext` `runAsNonRoot: true`, `runAsUser: 10001`, `fsGroup: 10001`;
  container `securityContext` `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`
  (`packaging/chart/acp/values.yaml:170-178`).
- **Graceful worker shutdown** — `terminationGracePeriodSeconds: 300`
  (`worker-deployment.yaml:55`), against an application that does drain on SIGTERM
  (`api/worker_main.py:37,56`).
- **No public worker ingress** — no Service is rendered for the worker tiers, and
  `test_packaging_chart.py::test_private_workers_render_a_policy_that_admits_nothing` asserts it.
- **Probes where they belong** — `test_the_api_gets_both_probes_and_they_are_not_the_same_endpoint`
  and `test_workers_get_no_http_probes`. **Both of those were green while the chart was wrong**, and
  the paragraph below says how.
- **Silent prerequisites already fail `acpctl doctor`** — KEDA absent, a non-enforcing CNI, and a
  missing External Secrets Operator are blockers, and a check that could not run is a blocker rather
  than a pass (`packaging/cli/acpctl/doctor.py`; `tests/test_packaging_doctor.py`, 35 cases).

**Two defects the rendered-manifest tests were green on**, found on 2026-09-08 by reading the
application against the chart rather than the chart against itself, and fixed:

- **Worker Deployments ran the API.** The worker container set no `command`, so it inherited the
  application image's CMD, which starts uvicorn (`deploy/public/Dockerfile`). A worker pod started,
  bound its port, reported Ready and claimed no jobs; the Deployment was healthy in every way
  Kubernetes can see, and the only symptoms were a queue that never drained and a tier that never
  wrote a heartbeat. `test_workers_get_no_http_probes` passed throughout — it asserts the chart
  declares no probes, which was true, while the container it rendered was an HTTP server.
- **The API readiness probe could not fail.** Readiness pointed at `/readyz`, whose handler takes no
  `Response` and never sets a status, so it answered 200 from a replica that could not reach the
  database — the exact replica a readiness gate exists to hold traffic away from. `api/routes/
  system.py` names `/probe/readyz` as "the ONE route a platform probe may point at" and explains why
  neither of the others can be. `test_the_api_gets_both_probes_and_they_are_not_the_same_endpoint`
  passed because it pinned the path the chart had, not a path that can return 503.

Both are one line of template each. What is worth keeping from them is the shape: a rendered-manifest
test compares the chart against itself, so a chart that renders the wrong thing consistently passes.
Neither defect was reachable without reading the application the chart deploys, and neither would
have survived one `helm install` on a real cluster — which is the argument for the blocking gap
below, made from the inside.

**What is missing.** No `topologySpreadConstraints` anywhere in the chart. No `seccompProfile`, so
the rendered pods do not meet the restricted Pod Security Standard as written, and
`readOnlyRootFilesystem` is `false` by default. No PersistentVolumeClaim and no volumes at all —
worker scratch is the node's ephemeral storage, bounded only by the limit above. The PDB renders
only for the `high-availability` profile and only for the API tier
(`values.py`: `"enabled": rt["profile"] == "high-availability"`; `templates/pdb.yaml`), which is a
recorded decision but means a standard-production install has no disruption budget on any tier. No
backup or restore Job, which PRD S5.2 lists as part of the Kubernetes package. Langfuse is deployed
ungated by Compose and rendered by nothing in the chart — asserted, deliberately, by
`test_packaging_chart.py::test_compose_deploys_what_the_chart_omits`.

**The blocking gap: there is no reference Kubernetes version, and no cluster to render against.**
The only version fact in the repository is `doctor.MINIMUM_KUBERNETES = (1, 23)`
(`packaging/cli/acpctl/doctor.py:42`), a floor derived from when `policy/v1` and `autoscaling/v2`
went stable — not a version anything has been validated on. There is no `kind`, `k3d` or `minikube`
reference anywhere in the repository; CI installs helm (`ci.yml:210`, `scripts/install_helm.sh`)
solely so `helm template` and `helm lint` can run. Every hardening claim above is therefore a claim
about text. "No authoritative output lives only on ephemeral storage" is the sharpest example: the
inventory records scratch as a disposable volume and
`tests/test_packaging_inventory.py::test_worker_scratch_is_declared_and_disposable` asserts the
declaration, but nothing has ever observed where a remediated file lands.

**Next step.** Name a reference Kubernetes version and stand up a disposable cluster in CI. Until
one exists, hardening work cannot be distinguished from hardening-shaped YAML — and the two
prerequisites `doctor` was built for (KEDA, an enforcing CNI) have themselves only been tested
against `tests/packaging_kubectl_fake.py`.

---

## C. Portable acceptance suite

**What exists.** Nothing of the ten scenarios. There is no `packaging/tests/` directory at all; PRD
S18 names `packaging/tests/{contract,smoke,upgrade,disaster-recovery}/` and none of it has been
created. The closest existing artifact is `packaging/chart/acp/templates/preflight-job.yaml`, a
post-install hook that reports connectivity and does not gate — useful as an in-cluster probe, but
it is one job, it produces no structured report, and `preflight.backoffLimit: 0` with
`hook: post-install,post-upgrade` means its result is advisory by design.

What the repository does have is the vocabulary the scenarios would be written against:
`inventory.LANE_JOB_TYPES` (the job types each worker role claims, pinned to `api/core.py` by
`test_packaging_chart.py::test_the_queue_lanes_match_the_application`), the tier/role mapping in
`inventory.TIER_ROLE`, and `acpctl status`, which already reads a running release and reports health
and drift with documented exit codes (`packaging/cli/acpctl/status.py`;
`tests/test_packaging_status.py`, 29 cases against a fake kubectl).

**What is missing.** All ten scenarios, the runner, the structured report, and the gate that refuses
a `supported` label unless the mandatory cases pass. `presets.SUPPORT_STATUS` currently marks
`compose` as `supported` and every Kubernetes platform as `planned`, and its comment already defines
`supported` as "a reference deployment in this repository runs the contract suite against it" — a
definition no target on Kubernetes can meet, because the suite does not exist.

**The blocking gap: eight of the ten scenarios need a lifecycle command that exits 2.** Restart of
each worker tier mid-job, scale-up and graceful scale-down, upgrade from the previous release,
backup-then-restore, and dependency degradation all presuppose something installed, and installing
is `acpctl install`. Two scenarios — API readiness/version and worker registration/heartbeat — could
in principle be written against a hand-run `helm install`, which is worth knowing, because it means
the suite is not blocked *end to end* on workstream D: its first two cases are blocked only on
having a cluster and images.

**Next step.** Write the report schema first — target, release digests, scenario list, timings,
artifacts — and have the first two scenarios emit it against a manually installed release. A schema
with two scenarios in it is a thing the other eight can be added to; ten scenarios with no report
format is a thing nobody can consume.

---

## D. `acpctl` lifecycle

**What exists.** Eight commands, all read-only: `init`, `validate`, `plan`, `inventory`, `values`,
`adapter`, `doctor`, `status`. Exit codes are documented and tested — `validate` 0/1; `doctor` and
`status` 0/1/2 with 2 reserved for "the cluster could not be reached, so nothing was established",
which is the distinction a retry loop needs. The read-only guarantee is enforced rather than
asserted: `tests/test_packaging_cli.py::test_no_command_writes_anything` patches `open`, and the
kubectl allow-list refuses every mutating verb
(`tests/test_packaging_doctor.py::test_acpctl_refuses_to_run_a_mutating_kubectl_verb`, parametrized
over a dozen verbs). `init -o` refuses to overwrite, with no `--force`.

**What is missing.** All seven lifecycle commands. `packaging/cli/acpctl/cli.py:27-35` lists
`install`, `upgrade`, `rollback`, `backup`, `restore`, `uninstall` and `support-bundle` in
`NOT_YET_IMPLEMENTED`; each parses its arguments, prints the phase it belongs to and returns 2
(`_unimplemented`, `cli.py:434`), which
`test_packaging_cli.py::test_unimplemented_commands_refuse_rather_than_silently_succeeding` pins so
none of them can become an accepted-and-ignored no-op.

**The blocking gap: `install` has nothing to pin.** The committed `values.py` emits `"digests": {}`
unconditionally, with
the comment that an empty map is an honest "not yet resolved" rather than a default that would
deploy a tag — so no install this repository can produce is digest-pinned. The chart is ready
(`acp.image` prefers a digest), `status` is ready (it compares releases on the
`app.kubernetes.io/version` label precisely so a digest-pinned install is not read as drift —
`tests/test_packaging_status.py::test_a_digest_pinned_install_is_not_reported_as_drift`), and
`install` is the missing middle: it is specified as the command that resolves digests and verifies
signatures, against a registry that holds none of the eight images and a signing process that does
not exist. Writing `install` before workstream A ships means writing the digest-resolution path
against nothing, and the dependency order (`install` → `upgrade` → `rollback` → `uninstall` →
`backup`/`restore` → `support-bundle`) means that first command gates the rest.

`support-bundle` is the one command with no such dependency — it reads a running installation and
redacts, which `status` and `doctor` already demonstrate the read half of. It is last in the
dependency order and could be built first if the goal were a usable command rather than a milestone.

**Next step.** Do not start `install`. Resolve the artifact-set disagreement in A first; `install`'s
first job is to turn eight names into eight digests, and today it would be turning eight names into
four image references under different names.

---

## What blocks a disposable-cluster acceptance run today

Ordered, smallest first dependency at the top.

1. **The chart and the plan must agree on the artifact set.** Four rendered image references against
   eight planned ones, with two names in common, and `acp-migrations`/`acp-preflight` not existing as
   chart components at all. This is the smallest first dependency: it is a decision plus one test,
   needs no cluster, no registry and no CI change, and every item below is ambiguous until it is
   made.
2. **Something must build the images the chart names.** Today `deploy/public/deploy.sh` builds
   `acp-app` and `acp-grafana`; the chart pulls `acp`, `acp-worker`, `acp-ollama-gateway` and
   `acp-grafana`. Three of those four references resolve to nothing in any registry, so
   `helm install` of the shipped example cannot pull.
3. **A registry the acceptance run can pull from**, and a tag or digest convention for it. The
   example's `runtime.imageRegistry` is a production ACR; an acceptance run needs a target that a CI
   job can push to and a throwaway cluster can read.
4. **A disposable cluster in CI.** No `kind`, `k3d` or `minikube` reference exists anywhere in the
   repository. `helm` is installed only to render.
5. **`acpctl install`.** Exits 2 today. Everything from scenario 3 onward — queue processing, restart
   mid-job, scale-down, upgrade, restore — presupposes it.
6. **The acceptance report format**, without which ten passing scenarios produce ten passing
   scenarios and no artifact anybody can compare across runs.
7. **Digest resolution and signature verification**, which is the point at which the run stops
   being a smoke test and starts being evidence about a specific release.

Items 1-3 are prerequisites for a manual `helm install`. Items 4-7 are what turn that into a
repeatable acceptance run.

## Not in scope for the MVP

- **The AKS adapter.** `packaging/docs/azure-adapter.md` specifies what an adapter must create and
  emits no Terraform or Bicep by design. `deploy/public/` keeps deploying Container Apps, and PRD S22
  forbids replacing it before parity is demonstrated. Nothing in this report proposes retiring
  `deploy/public/` or `deploy/compose/`.
- **On-prem certification.** PRD S4 excludes supporting arbitrary Kubernetes distributions without
  certification tests; the MVP validates one reference version, not a distribution matrix.
- **EKS and GKE.** PRD S21 phase 4. `presets.SUPPORT_STATUS` marks both `planned` and should keep
  saying so.
- **Air-gapped bundles.** PRD S17, phase 5. It depends on signed images and SBOMs, so it is
  downstream of workstream A rather than parallel to it.

## Summary

`verified` would mean acceptance evidence from a real cluster. Nothing here has any, so nothing here
is `verified`.

| Workstream | State | Evidence | Blocker | Next action |
|---|---|---|---|---|
| **A. Release artifacts and supply chain** | in progress | The `ACPRelease` contract, `acpctl release verify`, and `--release` on `values`/`plan` (`tests/test_packaging_release.py`), which reconcile the plan's eight names, the chart's four references and the one application artifact — and render every image by digest | Nothing builds, signs, SBOMs or scans an artifact, so no real manifest exists and CI has no release to fail on | Build the release images in CI and emit a signed manifest from that build |
| **B. Helm production hardening** | in progress | Requests/limits with `ephemeral-storage` on every workload; non-root pod security; `terminationGracePeriodSeconds: 300`; no worker Service; `doctor` blocks on KEDA, CNI and ESO (`tests/test_packaging_doctor.py`) | No reference Kubernetes version (only `MINIMUM_KUBERNETES = (1, 23)`); no disposable cluster; no topology spread, no seccomp profile, no backup/restore Job | Name a reference version and stand up a throwaway cluster in CI |
| **C. Portable acceptance suite** | not started | None — no `packaging/tests/`; the preflight hook is advisory (`backoffLimit: 0`, post-install) | Eight of ten scenarios need `acpctl install`, which exits 2; the first two need only a cluster and images | Define the structured report format and emit it from the two readiness scenarios |
| **D. `acpctl` lifecycle** | in progress | Eight read-only commands with documented exit codes; write-refusal and kubectl-verb allow-list both tested; the seven lifecycle commands refuse rather than no-op (`cli.py:27-35`) | `install` has nothing to pin to: the release contract exists but no build produces a manifest, so there are no real digests and no signature to verify | Hold `install` until a build emits a manifest; `support-bundle` is the one command with no upstream dependency |
