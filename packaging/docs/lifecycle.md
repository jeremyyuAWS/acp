# Installation lifecycle — `install`, `uninstall`, `backup`, `restore`

What these commands do, what they refuse to do, what they write down, and what has **not** been
proven about them. Two entries in PRD §10's command list — `upgrade` and `rollback` — still exit 2
and name the phase they belong to.

> **No target is `supported`, and nothing here changes that.** These commands have never been run
> against a real Kubernetes cluster in this repository's tests or CI. Every test below drives them
> through an injected runner that answers the way helm and kubectl are *documented* to answer. That
> is enough to establish the refusals, the exit codes, the idempotence and the record's shape; it
> establishes nothing about a real API server. `packaging/docs/service-inventory.md` continues to
> report `compose` as the only `supported` platform, and an acceptance run is what would change it.

---

## The mutation boundary

`acpctl` reads clusters through `cli/acpctl/cluster.py`, whose kubectl allow-list contains
`version`, `api-resources` and `get` and nothing else — that refusal is what makes `doctor` and
`status` safe to point at production from a laptop, and it is asserted against a dozen mutating
verbs in `tests/test_packaging_doctor.py`.

**Installing did not widen that list.** Every command that can change something lives in
`cli/acpctl/helm.py`, behind its own narrower allow-list:

| Permitted | Why |
|---|---|
| `helm install` / `upgrade` / `uninstall` | the install and the removal |
| `helm get` / `status` / `list` / `history` / `template` | reads and renders |
| `kubectl get` | reads |
| `kubectl logs job/<name>` | what a backup or restore Job says it did — **only** a `job/` target |
| `kubectl create namespace` \| `configmap` | the install target, and the install record |
| `kubectl create job --from=cronjob/<name>` | running the backup CronJob now — **only** with `--from` |
| `kubectl apply -f -` | the install record, and the chart's restore Job — stdin only, never from a path |
| `kubectl scale deployment --replicas=<n>` | quiescing for a restore — never `--all`, never without a count |
| `kubectl delete configmap acp-installation` | that record, by name |
| `kubectl delete pvc -l app.kubernetes.io/instance=<release>` | volumes the release owns, by selector — never by name, never `--all` |

Anything else raises `ForbiddenCommand`. `helm rollback` is deliberately absent even though it is
a helm subcommand acpctl will eventually need: an allow-list that pre-authorises the verbs of
unimplemented features is not an allow-list.

The delete guard is resource-scoped because `helm uninstall` can only remove what a release owns
while `kubectl delete` can remove anything the kubeconfig can reach, and "the uninstall deleted the
wrong namespace's database" has no undo.

**Four of those rows arrived with `backup` and `restore`, and the widening is the part worth
reviewing.** `create job` is permitted *only* with `--from=cronjob/…`, so the pod template comes
from an object the chart rendered rather than from a command line acpctl assembled — without that
flag, `kubectl create job --image=… -- <command>` is a shell inside the namespace holding the
database. `logs` is permitted *only* for a `job/` target, never a pod and never a selector: the two
Jobs' own output is a far narrower read than application logs, which carry document names and user
identifiers and are the support bundle's business, where every line goes through the redactor.
`apply` is unchanged in mechanism and **widened in source** — the manifest may now also be a
`helm template -s` render of the chart's restore Job, so it is no longer one acpctl authored end to
end.

`scale` is the broad one, and the honest description of its bound is a split: **the guard bounds
the kind and forbids `--all`; it cannot see which Deployments a caller picked.** `backup.py` only
ever names Deployments it read back from `app.kubernetes.io/instance=<release>`, and
`tests/test_packaging_backup.py::test_quiesce_scales_only_deployments_the_release_owns` is what
holds it to that. That is a caller discipline asserted by a test, not something the guard proves.

---

## Exit codes

The same three the read-only commands use, for the same reasons.

| Code | `install` | `uninstall` |
|---|---|---|
| **0** | installed and **verified**, or already installed and identical (a re-run is a no-op) | the preview was printed and nothing changed, or the removal completed |
| **1** | refused (unpinned, preflight blocker, namespace conflict, cancelled), failed, or **succeeded but could not be verified** | refused, the removal did not complete, or there was nothing here to remove |
| **2** | usage error, unreachable cluster, or nobody to answer the confirmation prompt | usage error (no `--data-policy`, no `--confirm-name` for a delete) or unreachable cluster |

| Code | `backup` | `restore` |
|---|---|---|
| **0** | the Job ran and its log **names the dump it wrote** | the preview was printed and nothing changed, or the restore completed and said how many tables it restored |
| **1** | refused (no release, no backup CronJob), the Job failed, or it **completed naming no dump** | refused, the render failed, or the Job failed — including its own refusal to run under a live application, which changes nothing |
| **2** | usage, unreachable cluster, or a Job this command stopped watching | usage (no `--from`), unreachable cluster, or a Job this command stopped watching |

Three of those are worth spelling out.

**Success is never inferred from silence.** `helm install` without `--wait` exits zero when the API
server *accepted* the objects, not when the application came up. `acpctl install` waits, then asks
helm what the release status actually is, and an install whose result it could not read exits **1**.
An installer that exits 0 for a result it did not observe is the failure this whole command set is
written against — and it is the easy failure to fall into, because everything it ran returned zero.

**Nothing to remove is a 1, not a 0.** "We removed nothing" is a different answer from "we removed
it", and a decommissioning script must not be able to report a namespace clean that it never
touched.

**A backup this command stopped watching is a 2, not a 1.** A timeout means the Job may still be
running and may still succeed; the only true statement is that `acpctl` stopped looking. Calling it
a failure sends an operator to re-run a dump that is in progress, which on a large database is the
least useful thing available at that moment.

---

## `backup`

> **Enabling the backup can make `acpctl install` roll the release back, and the error will not
> mention backups.** `helm --wait` waits for every PVC to be **Bound**. The backup claim is mounted
> by exactly one pod — the backup Job — which does not exist until the CronJob fires, so on a
> StorageClass with `volumeBindingMode: WaitForFirstConsumer` (kind's local-path, AWS gp3, Azure's
> managed-csi default) it stays Pending. `install` passes `--wait --atomic`, so the release rolls
> back with `context deadline exceeded`. Measured on the reference cluster, run `34241201489`.
>
> Point `backup.storage.existingClaim` at a claim that is already Bound, or give
> `backup.storage.storageClassName` a class with `volumeBindingMode: Immediate`. A claim with no
> consumer has nowhere to bind; no amount of chart templating changes that.
>
> **Not yet checked by `doctor` or refused by `install`**, and it should be: both already read
> StorageClasses, so reading `volumeBindingMode` and warning when `backup.enabled` meets a
> WaitForFirstConsumer default is a small, named follow-up rather than a gap to leave implicit.

One command: run the chart's backup CronJob now, wait, and read back what it produced.

```
acpctl backup acp.yaml -n acp-production
acpctl backup acp.yaml -n acp-production --json | jq .file
```

It **acts immediately** — there is no preview and no `--yes`, unlike every other mutating command
here. That asymmetry is deliberate: a preview earns its friction where the command destroys
something, and a backup writes a file.

1. **Find the CronJob by label**, `app.kubernetes.io/instance=<release>,app.kubernetes.io/component=backup`.
   Not by the name `<release>-backup`: the chart names it `<fullname>-backup`, and the fullname is
   not the release name whenever `fullnameOverride` is set. A computed name would find nothing and
   report "this installation takes no backups" about one that does — wrong in the direction where
   the operator stops looking.
2. **Refuse if there is none**, naming the three values that enable it, two of which have no
   default because they are decisions (`backup.schedule` is the RPO; `backup.retentionDays` is the
   retention policy).
3. **`kubectl create job --from=cronjob/<name>`.** The pod template comes from the CronJob.
4. **Wait, then read the Job's log**, and parse the line the backup writes about itself:
   `wrote /backups/acp-….dump (3138 bytes, 9 objects)`. That record is what `--json` emits, and it
   is the machine-readable "backup age" PRD §14 asks for.
5. **A Job that says `Complete` and names no dump exits 1.** Every command this ran returned zero;
   the log is the only thing that can tell the difference between a backup and an accepted request.

## `restore`

**Previews by default and changes nothing without `--yes`.** It drops and recreates every object in
the database, so the preview prints what it replaces, what it does *not* — object storage is not
rewound, so afterwards the database and the artifact store disagree about anything produced between
the dump and now — and how.

```
acpctl restore acp.yaml -n acp-production                       # what dumps are there?
acpctl restore acp.yaml -n acp-production --from acp-….dump     # preview
acpctl restore acp.yaml -n acp-production --from acp-….dump --quiesce --yes
```

**There is no `--from latest`.** After a bad migration the newest backup is the one you do not
want. Run without `--from` and the command lists the dumps the backup Jobs still on the cluster
reported writing — which is *not* a listing of the volume (the CronJob's history limits bound it),
and says so, because a name missing from it may still be on the claim.

**`restore.confirm` is read off the cluster, not recomputed.** The chart requires it to equal
`acp.fullname`; reimplementing helm's fullname rule here would be a second definition of somebody
else's contract, so it is the CronJob's own name with `-backup` removed.

**The Job is rendered from `helm get values`, not from the document.** An install may have carried a
release manifest's digests, a `--set`, or a second values file; a Job rendered from the document
alone can differ from the workloads it is restoring underneath — different image, different secret
name, different security context.

**And the name it polls for comes back out of the rendered manifest.** `templates/restore-job.yaml`
truncates to 63 characters, so a recomputed name would agree until a long release name or run id
crossed that, at which point the command would poll for a Job that does not exist and time out
while the restore ran perfectly.

### `--quiesce`

The restore Job refuses while any other session is on the database — correct, and the step
operators skip. `--quiesce` does it properly:

1. Read the release's Deployments and their replica counts, by `app.kubernetes.io/instance` label.
2. **Write those counts into the install-state ConfigMap before scaling anything.** A run
   interrupted between the scale-down and the scale-up otherwise leaves an application at zero with
   nothing on the cluster saying what it should be.
3. Scale to zero, restore, scale back — **including when the restore failed**. A restore that fails
   is a bad afternoon; one that fails and leaves the tiers at zero is an outage.
4. Clear the record on the way out, so the next run does not resume from stale counts.

**It refuses outright when there is nowhere to record the counts** — a release installed by hand
has no `acp-installation` ConfigMap. That is a legitimate situation and still not one in which this
command may take the tiers down.

An interrupted run is resumed from its own record rather than from the live counts, which are zero:
scaling "back" to zero would leave the outage in place.

---

## `install`

```bash
python -m acpctl install packaging/examples/standard-production.acp-deployment.yaml \
  -n acp-production --release-manifest release.json --yes
```

It runs, in this order, and stops at the first refusal:

1. **Validate the document.** An invalid document is refused before anything is contacted.
2. **Load and validate the release manifest** (below), then **resolve digests**. A manifest that
   fails `acpctl release verify`'s own rules is refused — not read partially, not installed and
   reported afterwards. With no manifest at all, refused unless every enabled image component has
   a digest, or `--allow-unpinned` is passed.
3. **Preflight** — the `acpctl doctor` checks, *imported* rather than reimplemented, so a check
   added there gates installs from that moment. Any blocker refuses; so does a blocking check that
   could not be run, because the checks that cannot run are the ones guarding failures that are
   otherwise silent. `--skip-preflight` proceeds and is recorded in the state.
4. **Namespace isolation.** Refused if the namespace already holds a different ACP installation —
   a different release name, a different deployment document, or a foreign ACP helm release —
   unless `--adopt` is passed and recorded. Two helm releases with different names install side by
   side without a word from helm, and the result is two installations sharing PVC names, a
   NetworkPolicy and a Postgres connection budget computed for one of them. An installation record
   that could not be *read* is also a refusal: an unreadable check is not an empty namespace.
5. **Idempotence.** If the document, the release manifest and the rendered values are unchanged
   and helm reports the release deployed, the install does nothing, exits 0, and appends no history
   entry. A re-run is not an event.
6. **The plan, then consent.** `acpctl plan`'s output is printed and confirmation is required:
   `y/N` on a terminal, or `--yes`. Without a terminal and without `--yes` the command exits **2** —
   silence is not consent, and the missing thing is a flag rather than something wrong with the
   cluster.
7. **Install.** `helm upgrade --install --atomic --wait`, so a first install and a re-run are the
   same command and a failure rolls back rather than leaving half a release behind.
8. **Verify, then record.**

### Digests, not tags

PRD §5.1 requires releases to deploy by immutable digest. A tag is a moving reference: two installs
a week apart from the same values file can run different code, and an installation that cannot say
exactly what it ran cannot be audited or reproduced.

So `install` refuses unless every image component the render *actually enables* has a
`sha256:…` digest. Only the enabled ones: a document with Ollama switched off renders no Ollama
Deployment, and demanding its digest would push the operator toward `--allow-unpinned`, which
switches pinning off for the components that do matter.

`--allow-unpinned` installs from tags, prints a prominent warning, and is recorded as
`release.pinned: false` in the install state — so the next reader can tell an audited release from a
hopeful one.

### The release manifest — one contract, one reader

`--release-manifest <path>` takes an **`ACPRelease`** document — the release-manifest contract
defined by `packaging/schema/acp-release.schema.json` and `packaging/cli/acpctl/release.py`, with
`packaging/examples/example.acp-release.yaml` as the worked example. YAML or JSON; the JSON path
needs no PyYAML, for the air-gapped bundle (PRD §17).

**`install` does not parse it.** It calls `release.load_manifest` and `release.validate` — the same
code `acpctl release verify`, `acpctl plan --release` and `acpctl values --release` run — and reads
three things off the result: the chart digests, the chart repositories, and the version. PRD §6
says not to let parallel work create multiple release-manifest formats, and this is that rule
applied to the reader as well as the writer: `install.py` used to carry a narrow reader of its own,
written before the contract existed, and two readers of one format drift *silently* — the copy
nothing else runs is the one that goes wrong, and the install is where the wrong digest lands.

A manifest that fails validation is **refused (exit 1) with the findings printed**, and nothing is
contacted. What that now covers, beyond the digest shape and revision agreement the old reader
checked:

- one **source revision** across the whole release (`release.mixed-revision`) — an API and a worker
  from different commits is a class of bug nobody can reproduce afterwards;
- a **signature** declared for every artifact (`release.unsigned`, PRD §5.1/§13) and an **SBOM**
  for every artifact (`release.no-sbom`);
- **amd64** on every artifact, with arm64 recorded per image rather than claimed release-wide;
- **unique component names**, every logical image `acpctl plan` names served by exactly one
  artifact, and every image the **chart** pulls backed by exactly one artifact — a chart image
  nothing backs is the silent case, because the chart falls back to the tag and the install
  succeeds *unpinned*;
- the release's `metadata.version` **matches the document's `runtime.version`**
  (`release.version-mismatch`), because the installation record states one version and it is the
  document's.

Warnings (a partial-arm64 release, a registry in a reserved TLD) are printed and do **not** refuse.

Two consequences worth stating:

- **One artifact can back several chart images.** `deploy/public/deploy.sh` builds a single
  application image that runs the API and every worker role, so `api` and `worker` are pinned to
  the same digest by the same component. The old reader's alias table — `acp-web-api`,
  `acp-discovery-worker`, … mapped onto chart roles — is gone; the manifest states the mapping
  outright in `chartImages`.
- **The manifest's `repository` beats the chart's default.** The chart's `image.repository` and
  `image.workerRepository` default to `acp` and `acp-worker`, names this repository's build does
  not produce; the manifest names what was built (`acp-app`). The chart-derived names remain the
  fallback for an install given no manifest — where the alternative is not a better name but none.

Nothing here contacts a registry, so a *declared* signature is not a *verified* one and a digest is
not proven to exist. Verifying against the registry is still future work (PRD §13).

---

## The install state — `configmap/acp-installation`

PRD §20.12: every deployment produces a redacted, immutable installation manifest. It is written as
a ConfigMap in the release namespace (so it travels with the cluster, not with whoever ran the
install) and printed on stdout with `--json`.

```yaml
apiVersion: packaging.acp.mova.io/v1alpha1
kind: ACPInstallation
installation:
  name: acp-production          # the deployment document's metadata.name
  namespace: acp-production
  releaseName: acp-production   # the helm release
  profile: standard
  platform: azure
  environment: production
  version: "2026.9"
document:
  path: packaging/examples/standard-production.acp-deployment.yaml
  sha256: sha256:…              # the reviewed input, byte for byte
release:
  revision: 1                   # the helm revision this landed as
  version: "2026.9"
  pinned: true                  # false when --allow-unpinned was used
  components:
    # The repositories and digests come from the release manifest (above), so `api` and `worker`
    # share one digest here: one built artifact backs both of the chart's images.
    api:     {repository: acp-app, digest: "sha256:…"}
    worker:  {repository: acp-app, digest: "sha256:…"}
  manifestSha256: sha256:…      # null when no release manifest was given
chart:
  name: acp
  version: "0.1.0"
  appVersion: "2026.9"
  valuesSha256: sha256:…        # the rendered values, digests included
recordedAt: "2026-09-08T11:04:00Z"     # RFC3339, UTC
acpctlVersion: 0.1.0-alpha
flags:
  skipPreflight: false
  adopted: false
  allowUnpinned: false
history:
  - {action: install, at: "2026-09-08T11:04:00Z", helmRevision: 1, result: ok}
```

- **It is not a helm-managed object.** If the chart rendered it, `helm uninstall` would delete it
  with the release, and the record of what was installed would vanish at the moment somebody most
  needs it. `acpctl` writes it and removes it itself.
- **It contains no secrets, and that is checked at write time**, not only in a test. The document
  holds secret *references*, never values — but a reference name can name a customer or an
  environment, and a connection string here would be a credential published to a ConfigMap that
  anything with `get configmaps` can read (PRD §13, §20.6). `state.secret_leaks()` runs before every
  write and fails the install rather than publishing.
- **The three hashes are what make a re-run a no-op**: the document, the rendered values (which
  include the resolved digests) and the manifest file. A run whose last recorded attempt *failed*
  is never treated as identical — re-running is the point.
- History is capped at the most recent 50 entries, so the record degrades by losing the oldest
  events rather than by failing to write at all.

---

## `uninstall` — and the data-retention policy

```bash
python -m acpctl uninstall <document> -n acp-production                       # preview, changes nothing
python -m acpctl uninstall <document> -n acp-production --yes --data-policy retain
python -m acpctl uninstall <document> -n acp-production --yes --data-policy delete \
  --confirm-name acp-production
```

**It previews by default.** With no `--yes` it runs no command that could change anything —
asserted on the recorded command log, because "it printed what it would do" and "it did it and then
printed" produce the same exit code. The preview lists the helm release and its objects, the
install record, and this release's PersistentVolumeClaims.

**The retained list is printed as prominently as the removed one**, because it is the half that is
normally omitted:

| Retained, always, whatever `--data-policy` says |
|---|
| **Postgres** — supplied by the infrastructure adapter, not by the chart (ADR 0048) |
| **Redis** — same |
| **Object storage** — same; this is where corrected files and artifacts live |
| Secrets in the platform vault — referenced by the release, owned by you |
| The namespace itself, and anything else in it |

An operator who reads "uninstalled" and assumes their data went with it goes looking for a database
that is still running and still being billed; one who assumes it was kept when it was not has lost
it. Neither of those is acceptable, and printing the list is what prevents both.

**`--data-policy` has no default and is required with `--yes`.** `retain` and `delete` are opposite
answers to a question only the operator can answer, and a default would be acpctl answering it for
them, silently, in whichever direction somebody happened to prefer.

**`--data-policy delete` additionally requires `--confirm-name <release>`.** Deleting a
PersistentVolumeClaim destroys its contents with no undo, so the release name has to be typed rather
than agreed to; a mismatch is refused, because it is more likely to mean the wrong namespace than a
typo. Even then, `delete` can only remove **in-cluster PersistentVolumeClaims carrying this
release's `app.kubernetes.io/instance` label** — the allow-list makes anything else impossible. If
the release owns none, the command says exactly that rather than printing a reassuring "data
deleted" that describes no event.

**The removal is recorded before the record is removed.** The uninstall history entry is written
into the in-cluster state, then that ConfigMap is deleted along with the release — so the copy the
command prints (and `--json` emits) is the surviving record. The command says so; keep it.

An **invalid document can still be uninstalled**, which is the opposite of the install rule. A
document that has stopped validating still describes an installation that is running right now, and
refusing would strand the one most likely to need removing.

---

## What is tested, and what that does not prove

`tests/test_packaging_install.py` and `tests/test_packaging_uninstall.py` drive both commands
against an in-memory cluster injected as the command runner: no cluster, no helm on PATH, no
network. It is stateful, so `helm upgrade` really does make the release deployed and `kubectl apply`
really does store the ConfigMap — which is what lets idempotence be tested at all, and lets the
uninstall tests remove an installation the install tests produced.

Every refusal is asserted to have **mutated nothing**, read off the recorded argv through the same
allow-list the guard enforces, so a newly permitted write is counted without anyone remembering to
update a list in a test.

What that does not prove: these are the answers helm and kubectl are *documented* to give, not a
recording of a real cluster. The parsed surface is deliberately tiny — a release status, a
ConfigMap, a PVC list — and every field read is a long-stable one, which is the mitigation, not a
refutation. Until an acceptance run against a real cluster happens, no target moves to `supported`.
