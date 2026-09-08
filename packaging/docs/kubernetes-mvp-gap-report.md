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

**Four defects the rendered-manifest tests were green on**, found on 2026-09-08, and fixed. The
first three by reading the application against the chart rather than the chart against itself; the
fourth by installing it:

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
persisted. ExternalSecret, ScaledObject and TriggerAuthentication need CRDs this cluster does not
have — `doctor` reports both operators as blockers on a real cluster, which is its job — so those
three are skipped BY NAME, and a kind that starts depending on a CRD fails the step rather than
being skipped quietly.

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
| **B. Helm production hardening** | in progress | Requests/limits with `ephemeral-storage` on every workload; restricted pod security ENFORCED by the API server on a disposable cluster, not merely rendered; `terminationGracePeriodSeconds: 300` with a matching drain window; no worker Service; `doctor` blocks on KEDA, CNI and ESO (`tests/test_packaging_doctor.py`) | The cluster it installs on is `kindest/node:v1.31.4`, which is a version it RUNS on, not one anything is supported on — naming a supported distribution is PRD S4 and an owner decision; zone spreading is soft on every profile and unprovable on a one-node cluster, no `readOnlyRootFilesystem` (blocked on `PUT /rubric` writing into the image), no backup/restore Job | A backup/restore Job, then a PDB outside the high-availability profile |
| **C. Portable acceptance suite** | not started | None — no `packaging/tests/`; the preflight hook is advisory (`backoffLimit: 0`, post-install) | Eight of ten scenarios need `acpctl install`, which exits 2; the first two need only a cluster and images | Define the structured report format and emit it from the two readiness scenarios |
| **D. `acpctl` lifecycle** | in progress | Eight read-only commands with documented exit codes; write-refusal and kubectl-verb allow-list both tested; the seven lifecycle commands refuse rather than no-op (`cli.py:27-35`) | `install` has nothing to pin to: the release contract exists but no build produces a manifest, so there are no real digests and no signature to verify | Hold `install` until a build emits a manifest; `support-bundle` is the one command with no upstream dependency |
