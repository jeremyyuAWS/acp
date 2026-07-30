# How a change reaches production, and how the matrix keeps up

Two chains start from one event — a PR merged to `acp/main` — and then never touch again.

**Chain A** keeps the public WCAG matrix in step with the code. It is automatic and finishes in
minutes.

**Chain B** puts the code in production. It is now `deploy.yml`, but it runs on **manual
dispatch** — someone still decides when.

That asymmetry is the single most important thing on this page: **the matrix can be perfectly
accurate about code that is not deployed.** For most of 2026-07-29 it was, and automating the
build did not change it — a pipeline nobody triggers ships exactly as much as no pipeline. The
gap closes when the trigger becomes `push: [main]`, not when the workflow file lands.

```
                        ┌──────────────────────────┐
                        │   PR merged to acp/main  │
                        └────────────┬─────────────┘
                                     │
              ┌──────────────────────┴──────────────────────┐
              │                                             │
   ═══════ CHAIN A: matrix sync ═══════        ═══════ CHAIN B: app deploy ═══════
              │  (automatic)                                │  (deploy.yml — dispatch)
              ▼                                             ▼
   matrix-progress-log.yml                        1. pin  PIN=$(git rev-parse origin/main)
   scans the pushed commits:                         └─ gate: CI on PIN must be green
     (a) Matrix-Note: trailers → count            2. clone to /tmp/acp-deploy, checkout PIN
     (b) capability sources touched?                 └─ the shared checkout is written by many
              │                                         sessions; a build there is unreproducible
     repository_dispatch ──────────┐              3. dotnet build AcpScan.Cli -c Release
     (MATRIX_DISPATCH_TOKEN)       │                 └─ .NET Office analyser → bin/Release/net10.0
              │                    │              4. vendor worker-python  (41 modules)
              ▼                    ▼                 └─ GUARD: abort if < 41
   progress-log.yml         grid-drift.yml            └─ source is NOT in this repo
    gen_progress_log.py      gen_matrix_coverage.py  5. az acr build -r mdkaccessibilityacr
    gen_matrix_coverage.py   check_grid_drift.py        -t acp-app:<sha>-<ts>
    apply_progress_log.py                           6. HEALTH CHECK BEFORE  ← baseline
    apply_maturity.py       drift? → --apply on     7. az containerapp update --image
    bump_build.py             automation/grid-drift        acp-app   ─┐ image only:
              │                    │                       acp-worker ┘ 27 env + 9 secrets survive
              ▼                    ▼                          └─ BOTH, or fixes ship nowhere
   COMMIT → main            OPEN A PR (human)      8. verify /healthz + /readyz
              │                    │
              └────────┬───────────┘
                       ▼
              Netlify auto-deploy
              wcag-matrix.mova-io.app
```

---

## Chain A — matrix sync

### The sender

`.github/workflows/matrix-progress-log.yml`, on every push to `main`. It looks for two
independent signals and fires a `repository_dispatch` for each:

| signal | how it is detected | event |
|---|---|---|
| a commit opted into the public changelog | a `Matrix-Note:` trailer (see `scripts/gen_progress_log.py`) | `acp-progress-log` |
| a capability CEILING may have moved | the push touched a path in `gen_matrix_coverage.py --sources` | `acp-capability-change` |

The second is deliberately **not** opt-in. A ceiling can move without anyone writing a trailer,
and a cell claiming more than the code supports is a correctness bug rather than a changelog
omission.

The dispatch carries **no entry data** — it is a bare "something landed, go look". The generator
therefore lives in exactly one place, there is no 64 KB payload ceiling to design around, and a
dropped dispatch is self-healing because the far side regenerates from full history.

Requires the `MATRIX_DISPATCH_TOKEN` secret: `GITHUB_TOKEN` cannot dispatch across repositories.
Without it the job logs a notice and exits 0 rather than failing a push.

### The receivers

Both clone acp and run **its** generators — the matrix never reimplements them.

**`progress-log.yml`** → `gen_progress_log.py` + `gen_matrix_coverage.py`, spliced by
`apply_progress_log.py` and `apply_maturity.py`, then `bump_build.py`. It **commits straight to
`main`**.

**`grid-drift.yml`** → `check_grid_drift.py` against the freshly derived coverage. On drift it
applies to a branch and **opens a PR**.

### Why one commits and the other asks

| | Progress Log | Grid tiers |
|---|---|---|
| lands as | auto-commit | a PR a human reviews |
| because | a changelog entry is a **fact** — this commit shipped | a tier is a **judgement**, and code cannot make it |

This is not caution for its own sake. On 2026-07-29 the drift guard produced **14** proposals
and **2 were wrong** — one because acp contradicted itself, one because a missing remediation
lane made the tool fall back to an assessment-side value. A bulk auto-apply would have silently
corrupted both cells, and one of them was hiding an engine bug that a human reading the proposal
went on to find.

---

## Chain B — app deploy

**There is a pipeline now: `.github/workflows/deploy.yml`.** It runs `redeploy.sh` on a runner
rather than reimplementing it, so the guards below are the same guards — Actions → deploy → Run
workflow, optionally with a pin and a blue-green toggle.

Two things had to be true first, and only one of them was obvious. The build context had to be
complete from a checkout: the Dockerfile used to copy the PDF engine from a gitignored staging
directory a script filled from *outside* the repo, so a runner could never assemble it. ADR 0029
vendored the engine, which is what unblocked this. And `redeploy.sh` had to resolve `dotnet` from
PATH — `actions/setup-dotnet` never creates `~/.dotnet/dotnet`, so the old hard-coded default
would have failed on the one host CD runs on.

It is **manual-dispatch by default**. Deploying every merge is the goal, but the honest starting
point is a person pressing the button on a pipeline nobody has watched run; flip the trigger to
`push: [main]` once it has shipped uneventfully a few times. The `production` GitHub Environment
is what makes that safe — configure required reviewers there, not in the trigger.

**One-time setup, all of it outside this repo:**

| what | where |
|---|---|
| Azure OIDC federated credential for this repo | an App Registration → Federated credentials |
| `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | repo → Settings → Secrets |
| `ACP_FQDN` (the app hostname, no scheme) | repo → Settings → Variables |
| `production` environment + required reviewers | repo → Settings → Environments |

The service principal needs Contributor on the `mdk-accessibility` resource group and AcrPush on
the registry — no more. OIDC federation is used deliberately over a stored client secret: a
long-lived deploy credential in a repo secret is the thing you least want to rotate under pressure.

Until those exist the workflow fails at `azure/login`, which is the correct failure — it is the
only step that cannot be verified from here.

### Deploying locally

Every image in the registry before this was built from a laptop (`runType: QuickRun`,
`sourceTrigger: null`), and the script is still the way to do it by hand. It behaves identically
to the workflow, and its CI gate degrades to a loud "NOT CHECKED" rather than a silent pass when
`gh` is unavailable:

```bash
./deploy/public/redeploy.sh          # ACP_DRY_RUN=1 to stop before touching Azure
```

It performs exactly the sequence below, with every guard, and adds two things the hand-run
version could not:

**Dependency bases, so a source change stops paying for LibreOffice.** Measured 2026-07-29:
six ACR builds, every one 2m46s–3m14s. Almost none of that was the app — it was the apt layer
(LibreOffice writer/calc/impress plus a *downloaded* .NET 10 runtime), `pip install`, and
`npm install`, re-running every time. `az acr build` has **no `--cache-from`** (checked on az
2.86.0), so a QuickRun cannot reuse layers from a previous build.

Those layers now live in `acp-base-api` / `acp-base-web`, tagged with a hash of *only* their
inputs — `api/requirements.txt`, `frontend/package-lock.json`, and the two `Dockerfile.base-*`
files. Source is deliberately excluded from the hash: if a source edit moved it, the base would
rebuild every time and the split would achieve nothing. The bases rebuild only when that hash
moves, and `redeploy.sh` decides that by asking the registry, so nobody has to remember.

`deploy/public/Dockerfile` still defaults `BASE_WEB`/`BASE_API` to the upstream images, so a
first deploy — or anyone without the bases — builds from scratch exactly as before.

**Both apps updated concurrently.** `--no-wait` on each, then poll both. Sequential updates left
a window where `acp-app` and `acp-worker` ran *different images*, which the rule below forbids.

It also refuses to finish unless `/healthz` reports the new CalVer and `version_stamped: true` —
an image built without the build args runs perfectly well while every surface reports `dev`.

<details><summary>The eight steps it runs</summary>

```bash
PIN=$(git rev-parse origin/main)                 # 1. pin, and check CI is green on it
git clone --local . /tmp/acp-deploy              # 2. isolated tree
cd /tmp/acp-deploy && git checkout "$PIN"

dotnet build spike/dotnet/AcpScan.Cli -c Release # 3. Office analyser
cp -R "$ACP_PDF_ENGINE_SRC" deploy/public/vendor/worker-python
[ "$(find deploy/public/vendor/worker-python -name '*.py' | wc -l)" -ge 41 ] || exit 1   # 4.

az acr build -r mdkaccessibilityacr \            # 5. remote build, no local docker
  -t "acp-app:${PIN:0:7}-$(date +%s)" -f deploy/public/Dockerfile \
  --build-arg BUILD_VERSION=... --build-arg BUILD_TIME=... .

curl -s "$APP/healthz"                           # 6. baseline BEFORE deploying

az containerapp update -n acp-app    -g mdk-accessibility --image "$IMG"   # 7. image only
az containerapp update -n acp-worker -g mdk-accessibility --image "$IMG"

curl -s "$APP/healthz"; curl -s "$APP/readyz"    # 8. verify
```

</details>

### Why each guard exists

Steps 1, 2, 4 and 6 are scar tissue. Every one was added because it failed on 2026-07-29:

| step | what it prevents |
|---|---|
| **1** pin + CI gate | a build from a commit rewritten mid-run — produced an image from a sha that no longer existed, matching how `2553e6d` came to be in production while absent from git history |
| **2** isolated clone | `az acr build` uses the working directory as context, so a shared checkout bakes other sessions' half-finished work into the image. 17 files were uncommitted at the time |
| **4** module guard | an expired ACR token made the vendoring step a silent no-op — **0 modules** — which still builds, shipping an empty PDF engine |
| **6** health before | when the app returned 404 after a deploy there was no way to tell whether it had been broken by it. Both apps turned out to have been `Stopped` beforehand |

### Two things that must stay true

**Both apps move together.** `acp-app` and `acp-worker` run the *same image* and differ only by
entrypoint. Scanning happens in the worker, so updating only the app deploys the fixes nowhere
useful.

**Image-only updates.** `az containerapp update --image` leaves 27 environment variables and 9
secrets intact. Running `deploy.sh` instead would re-derive them from the environment — minting
a **new access code**, blanking `DATABASE_URL` to fall back to SQLite, and dropping most of the
rest. It is the right script for a first deploy and the wrong one for a redeploy.

---

## Self-healing

- **Monday 06:17 UTC cron** on `grid-drift.yml`
- **`workflow_dispatch`** on both receivers — re-syncs from scratch, no range state is kept
- The matrix regenerates from **full history** and de-duplicates by commit hash, so a dropped or
  missed dispatch is caught by the next one

## The guards that keep it honest

| where | guard | fails when |
|---|---|---|
| acp CI | `gen_progress_log.py --check` | rule code changed with no `Matrix-Note:` trailer |
| acp CI | assessment-lane gate | a `human` lane could return a certified PASS |
| acp CI | applier/detector parity | a fix is credited on a criterion no detector emits for that format |
| matrix CI | `check_log_covers_grid.py` | a cell **or ceiling** moved with no new Progress Log entry |
| matrix CI | `check_boot_order.py` | a function running at load reads a `const` declared below it |
| matrix CI | JS parse + CSS balance | the page would render broken |
| matrix | timestamps derived from the commit | — they cannot be typed, so they cannot be invented |

## Known weaknesses

- **No deploy pipeline.** Chain B is a person. Nothing links a merge to a running container, and
  nothing alerts when production falls behind `main`.
- **`worker-python` is vendored, not versioned.** It is not in this repo; step 4 copies it out of
  a running image. If that image is pruned, the chain breaks until the source is located.
- **The dispatch only fires on push to `main`.** Work on a branch is invisible to the matrix
  until it merges.
- **`acp-ollama` is a single always-on replica** at 4 CPU / 8 GiB, with a cold model load of tens
  of seconds.
