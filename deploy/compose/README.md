# Local / VPC stack — `docker compose`

Runs the **entire ACP platform** on one machine with no Azure and no MDK
dependency — exactly what a customer needs to run it inside their own VPC.

```bash
cd deploy/compose
cp .env.example .env          # edit secrets (see below)
docker compose up --build
```

| Service | URL | Notes |
|---------|-----|-------|
| `acp-app` | http://localhost:8077 | the platform (FastAPI + React SPA) |
| `grafana` | http://localhost:3000 | 10-panel ACP dashboard, anonymous viewer |
| `langfuse` | http://localhost:3001 | LLM tracing; self-register on first visit |
| `db` | localhost:5432 | Postgres 16 — `acpdb` + `langfusedb` |
| `test` | — | backend suite in the CI toolchain; `--profile test`, does not start with `up` |

## One build prerequisite

The `acp-app` image bundles **both analysis engines as compiled artifacts** (it does
not build them). The Python PDF engine now comes straight from the tracked tree
(`engine/pdf-analyser/`, ADR 0029) and needs nothing from you. Only the .NET CLI is a
compiled output, so before `docker compose up --build`:

1. **.NET Office CLI** — `spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll`
   must exist. Build it once:
   ```bash
   dotnet build -c Release spike/dotnet/AcpScan.Cli
   ```

If the CLI is missing the app still boots and HTML/PDF scans work; Office scans report
an engine-missing error per file.

Verify both engines actually loaded, rather than assuming — `/readyz` reports the PDF
engine directly, and a scan of the bundled corpus exercises all three analysers:

```bash
curl -s localhost:8077/readyz | jq .engines
```

## Running the backend suite

`pytest tests/` on a host without the full toolchain exits 1 with dozens of failures
across ~8 modules, and **none of them are repo breakage** — dotnet, pdfplumber, langfuse,
tesseract and friends are simply absent. That misreading has cost real time: on 2026-08-19
a session reported "32 pre-existing test failures" and carried the claim through four PRs
before it turned out to be its own venv. The `test` service is the answer to "is it me or
is it the repo".

It is behind the `test` profile, so it never starts with `docker compose up`. It builds
`deploy/test/Dockerfile` — the CI toolchain, nothing else — and **bind-mounts this repo at
`/app`**, so it runs your working tree, uncommitted edits included. No rebuild for a source
change; rebuild only when `api/requirements.txt`, `tests/requirements.txt`, a `.csproj` or
the Dockerfile itself moves.

**The suite:**

```bash
cd deploy/compose
docker compose --profile test run --rm test
```

**All four backend checks** — which is what CI's "Backend suite" job actually is:

```bash
docker compose --profile test run --rm test acp-checks
```

`pytest tests/` is only the first of the four. The other three (`gen_matrix_coverage.py
--check`, `gen_todo_status.py --check`, `gen_progress_log.py --check`) parse the repo rather
than test it, and the last one is the one that bites, because nothing local prompts you for
it: it fails when a commit touches `RULE_PATHS` — the bare prefix `api/remediate` matches
both `remediate_office.py` and `remediate_pdf.py` — without a `Matrix-Note:` trailer in its
message. `acp-checks` runs all four and reports each, rather than short-circuiting on the
first red. To check a whole branch the way a PR does, rather than only your last commit:

```bash
docker compose --profile test run --rm -e BASE_REF=main test acp-checks
```

Anything after the service name is the command, so a subset works the usual way:

```bash
docker compose --profile test run --rm test python -m pytest tests/test_alt_validator.py -q
docker compose --profile test run --rm test bash          # a shell in the toolchain
```

### What it measures, exactly

Measured on 2026-08-20 at `233e132`, serially, inside the image:

```
3425 passed, 38 skipped, 9 warnings   —   exit 0
gen_matrix_coverage.py --check        —   exit 0
gen_todo_status.py --check            —   exit 0
gen_progress_log.py --check           —   exit 0
```

**Zero failed, zero errored.** The 38 skips are not the image falling short, and they are
worth knowing one by one, because an image that silently skips part of the suite while
printing green is worse than no image at all:

| Skips | Reason | Runnable here? |
|-------|--------|----------------|
| 36 | `tests/test_rule_contract.py` — the rule's source is partner/vendored code (`digital-accessibility/…`, `deploy/public/vendor/worker-python/…`) that is not in this repo | **No, by design.** These skip on CI too; the paths do not exist on a clean checkout. |
| 2 | `tests/test_remediation_capability.py` — no local Ollama text/vision model answering | **No, deliberately.** ci.yml: "Ollama-backed tests self-skip here … so no model is needed and none is installed." Wiring the `ollama` service in would make this run diverge from the gate, not converge on it. |

Two things the image does NOT contain, both because CI does not either:

- **LibreOffice.** `tests/test_render_page.py` asserts the no-soffice contract directly
  (`render.can_render(".pptx") is (render._soffice() is not None)`), so installing it would
  exercise a different branch than the gate does.
- **The `worker-python` PDF engine as a separate checkout.** It has been vendored in-repo at
  `engine/pdf-analyser/` since ADR 0029, so `PDF_OK` is true from the mount and the PDF
  suites run. (`tests/conftest.py`'s docstring still describes the old out-of-repo
  arrangement; `tests/engines.py` is the current word.)

### Two tests reach the network

`tests/test_redeploy_pin_resolution.py` runs the real `deploy/public/redeploy.sh` with stubbed
`az`/`gh`, and the script does a genuine `git fetch origin` before it resolves the pin. The two
tests gate on an origin remote *existing*, not on it being reachable, so on a machine that
cannot reach `github.com` — offline, or behind a proxy the container does not inherit — they
fail rather than skip:

```
fatal: unable to access 'https://github.com/jeremyyuAWS/acp/': …
```

Nothing else in the suite needs the network. Ollama and Langfuse are absent on purpose (above),
and every other fixture is built on disk.

### One requirement on your checkout: full history

Clone normally. On a `--depth 1` clone the guards go **vacuous rather than red** —
`gen_progress_log.py --check` finds no commits to inspect and passes, which is why ci.yml
sets `fetch-depth: 0` explicitly. Measured: on a shallow clone,
`test_generation_succeeds_over_this_repos_real_history` fails with "the generator produced
an empty log over real history"; after `git fetch --unshallow` it passes. If you cloned
shallow:

```bash
git fetch --unshallow
```

### Postgres — up, but NOT wired into the suite

The service `depends_on` `db`, so Postgres is healthy before the suite starts and reachable at
`db:5432`. **`DATABASE_URL` is deliberately not set**, and that is not an oversight.

`api/store.py` picks its adapter from that one variable —
`_PgAdapter(_DATABASE_URL) if _DATABASE_URL else _SQLiteAdapter(...)` — so exporting it does
not "let the tests that want Postgres find it". It moves the **whole suite** onto Postgres, and
the suite's fixtures assume a private database per test (`tests/conftest.py` hands every
`Store` a fresh temp SQLite file). A single shared Postgres collides on primary keys.

Measured both ways, since this service originally did set it:

| | Result |
|---|---|
| `DATABASE_URL` unset | **3425 passed, 38 skipped, 0 failed** — exit 0 |
| `DATABASE_URL` → the `db` service | **240 failed**, 3180 passed, 38 skipped, 5 errors — exit 1 |

Isolated to one module with no other load, to be sure it was the variable and not the
contention: `tests/test_remediated_download_isolation.py` is 5 passed / exit 0 unset, and
1 passed + 4 errors / exit 1 set, with
`psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
"scan_runs_pkey"`.

CI has no Postgres at all, so leaving it unset is also what makes this run agree with the gate.
If you are writing a test that genuinely needs Postgres, set the variable for that run only
(`docker compose --profile test run --rm -e DATABASE_URL=… test …`) and expect the rest of the
suite to be red in that run.

### Notes

- The Office analyser CLI is built by the container's entrypoint, on first run, from the
  mounted source — into the gitignored `spike/dotnet/AcpScan.Cli/bin/Release/net10.0/`, which
  is the exact path `tests/engines.py` probes. Later runs reuse it. Force a rebuild with
  `-e ACP_REBUILD_ENGINE=1`. Built from the mount rather than baked into the image on
  purpose: a baked DLL would keep passing after the analysers changed underneath it.
- Build output is written into your tree as root, since the container runs as root. It is all
  gitignored (`bin/`, `obj/`, `__pycache__`), but `sudo` may be needed to delete it.
- No secrets are in this image and none should be added. `.env.example` is the pattern for
  anything configurable.

## First-run Langfuse wiring (one time)

Langfuse keys don't exist until the service is up:

1. `docker compose up --build` and wait for all four to be healthy.
2. Open http://localhost:3001 → sign up → create a project.
3. Project settings → API keys → copy the `pk-...` and `sk-...`.
4. Paste them into `.env` as `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.
5. `docker compose up -d acp-app` to restart the app with tracing enabled.

Scans run before step 5 still work — they just aren't traced.

## Data persistence

Postgres data lives in the `acp-db` named volume. `docker compose down` keeps it;
`docker compose down -v` wipes it (fresh databases on next up).

## Production hardening (before a real customer deploy)

- Replace the dev passwords in `.env` with secrets from your vault.
- Put a TLS-terminating reverse proxy in front (`acp-app` and `grafana` speak plain
  HTTP).
- For high trace volume, move Langfuse to v3 (adds ClickHouse + Redis + S3/MinIO) —
  v2 here keeps the dependency surface to a single Postgres for easy standup.
- Lock Grafana down: set `GF_AUTH_ANONYMOUS_ENABLED=false` and provision real users
  if the dashboards shouldn't be open inside the VPC.
