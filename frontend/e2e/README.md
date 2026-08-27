# Browser E2E — the real pipeline, in a real browser

`frontend/src/*.test.jsx` mounts components in jsdom. This suite drives Chromium against a
real vite build and a real FastAPI backend, so it covers what neither half can alone: sign-in,
the scan gate, the discovery wizard, SSE progress, and the analysers actually scoring files.

```bash
cd frontend && npx playwright test
```

That is the whole command — `playwright.config.js` starts the API and vite itself.

## What it exercises

Sign in → Discover → the 3-step discovery wizard → a real local scan → Assess → per-rule
WCAG findings read back off the finished scan record. No Google credentials, no SharePoint
token, no .NET build.

## The three things that make it deterministic

`scripts/e2e-api.sh` sets all of them up. Each exists because of a specific way the run goes
wrong without it:

**A fresh store.** `api/store.py` hardcodes sqlite at `<repo>/acp.db` with no env override.
A scan left `running` there blocks every later local scan — and the rejection surfaces as
`phase=discovered, files_found=0, done=true`, which reads as an empty corpus rather than as a
refusal. The script moves the store aside per run (to `acp.db.prev-e2e`, so a failed run is
still inspectable).

**In-process workers.** Assess fans out to the job queue (ADR 0007), and the UI's scan path is
`queue=true&fanout=true` — the toggle for the non-queued path was removed from the modal. With
the default `ACP_RUNTIME_MODE` the API runs zero workers and `App.doScan` throws
`no workers available`. `single-node` runs four in-process.

**A frozen corpus.** `ACP_LOCAL_CORPUS` points local scans at three `test-corpus/oracle/`
fixtures instead of `test-corpus/files`, which tracks the demo's needs and changes. PDF only.
Not Office, because those fixtures need the .NET CLI built and would otherwise score `None`,
making a missing optional build look like a scoring regression. And not HTML either, which is
the less obvious half: HTML *is* analysed by `POST /scans/{id}/assess`, but it is not in the
format list of any WCAG code in the app's default criteria, so the Assess screen counts HTML
files as excluded. Any exclusion sets `needsAck`, which disables the run button until an
operator confirms — so an HTML fixture adds no coverage, it just parks the suite on a disabled
button. A uniformly eligible corpus is what makes the happy path a happy path.

## VITE_SIM=false is the load-bearing one

`sim.js` reads `import.meta.env.VITE_SIM !== 'false'`, so **simulation is on unless that exact
string is set**, and in SIM mode `api.js` serves synthetic fixtures and never opens a socket.
Because SIM renders through the same components, every DOM assertion in this suite still
passes against it — a fully green run proving nothing.

That is why `pipeline.spec.js` records the requests the page actually made and fails if none
reached the backend, and why it asserts on the corpus file count and on named rule ids rather
than on "something rendered". A check that cannot fail is indistinguishable from one that
passed.

## Selectors

There are ~29 `data-testid`s in the app and none are on this path, so the suite leans on what
is actually stable here:

- `[data-wizard-forward]` / `[data-wizard-back]` — the only purpose-built hooks on the path.
- ARIA roles and labels. This is an accessibility product; the ARIA is deliberate and already
  asserted by unit tests. `role="dialog"[name="New discovery"]`,
  `role="region"[name="Discovery complete"|"Discovery in progress"|"Discovery stopped"]`.
- Semantic classes where there is no role: `.assesssummary`, `.assesssetup-run`.

Two traps worth knowing. Tab accessible names concatenate the label with its subtitle span
("Discover inventory · classify") and gain a hidden "completed: " prefix once the stage
finishes, so tabs are matched by substring, never by exact name. And there is no
"Assessment complete" string anywhere — the summary panel appearing is the signal.

## Ports

5174 and 8078, not the dev 5173/8077, so a run neither collides with nor quietly borrows a
`./scripts/run.sh` stack. Borrowing would be the worse failure: the suite would pass against
whatever corpus and store that one happens to hold.

## Sandboxes with a pre-installed browser

Set `ACP_E2E_CHROMIUM` to a chrome binary when the environment ships a browser from a
different Playwright release than `frontend/package.json` pins — otherwise launch fails with
`Executable doesn't exist at .../chromium_headless_shell-<n>`. CI runs
`playwright install chromium` and leaves it unset.
