# Installation lifecycle — `acpctl install` and `acpctl uninstall`

What these two commands do, what they refuse to do, what they write down, and what has **not**
been proven about them. Everything else in PRD §10's command list — `upgrade`, `rollback`,
`backup`, `restore`, `support-bundle` — still exits 2 and names the phase it belongs to.

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
| `helm get` / `status` / `list` / `history` / `template` | reads |
| `kubectl get` | reads |
| `kubectl create namespace` \| `configmap` | the install target, and the install record |
| `kubectl apply -f -` | the install record, from a manifest acpctl builds itself — never from a path |
| `kubectl delete configmap acp-installation` | that record, by name |
| `kubectl delete pvc -l app.kubernetes.io/instance=<release>` | volumes the release owns, by selector — never by name, never `--all` |

Anything else raises `ForbiddenCommand`. `helm rollback` is deliberately absent even though it is
a helm subcommand acpctl will eventually need: an allow-list that pre-authorises the verbs of
unimplemented features is not an allow-list.

The delete guard is resource-scoped because `helm uninstall` can only remove what a release owns
while `kubectl delete` can remove anything the kubeconfig can reach, and "the uninstall deleted the
wrong namespace's database" has no undo.

---

## Exit codes

The same three the read-only commands use, for the same reasons.

| Code | `install` | `uninstall` |
|---|---|---|
| **0** | installed and **verified**, or already installed and identical (a re-run is a no-op) | the preview was printed and nothing changed, or the removal completed |
| **1** | refused (unpinned, preflight blocker, namespace conflict, cancelled), failed, or **succeeded but could not be verified** | refused, the removal did not complete, or there was nothing here to remove |
| **2** | usage error, unreachable cluster, or nobody to answer the confirmation prompt | usage error (no `--data-policy`, no `--confirm-name` for a delete) or unreachable cluster |

Two of those are worth spelling out.

**Success is never inferred from silence.** `helm install` without `--wait` exits zero when the API
server *accepted* the objects, not when the application came up. `acpctl install` waits, then asks
helm what the release status actually is, and an install whose result it could not read exits **1**.
An installer that exits 0 for a result it did not observe is the failure this whole command set is
written against — and it is the easy failure to fall into, because everything it ran returned zero.

**Nothing to remove is a 1, not a 0.** "We removed nothing" is a different answer from "we removed
it", and a decommissioning script must not be able to report a namespace clean that it never
touched.

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
