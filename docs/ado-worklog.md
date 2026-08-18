# ACP — Delivery Log

Work on the Accessibility Compliance Platform. Grouped for Azure DevOps intake:
each top-level heading maps to a Feature, each bullet to a Task.

Repository: `jeremyyuAWS/acp` · 1,771 files · 1,067 commits total
**This log starts at 2026-08-01.** The project predates it by ~1,000 commits; earlier work
is not covered here. The `(#NNN)` references are GitHub PRs, not ADO work items.

ADO: `MovateAI-Foundry` / `AI-Foundry` · Epic **#3664** ACP — Accessibility Compliance Platform

---

## Feature: SharePoint as a document source · #4600

- Extended scanning from the signed-in user's OneDrive to full team sites (#156).
- Made remediated copies write back to SharePoint (#157). `SharePoint.jsx` imported
  `uploadToDrive` and `saveDriveScore` and never called either, so writing back was not
  possible at all. Built deliberately to the same shape as `/drive/upload` — multipart
  `scan_id`/`file`/`blob`, the same admin-configured mirror folder, the same
  `record_remediation` call — so a SharePoint write appears in the compliance record exactly
  like a Drive one.
- Sourced the write target from the scan rather than from the client. A Graph item id is
  unique only within its drive, so writing to the wrong `drive_id` does not error — it
  **succeeds, into somebody else's library**. The scan records the drive on every item it
  lists, which is what makes the write safe.
- Backed up the original before overwriting it (#158).
- Stopped re-ingesting remediated output as if it were new source material (#157).
- Made a one-site scan name the site it scanned instead of reporting "across OneDrive" (#169).
- Added frontend clients for the two SharePoint routes that had none (#167).
- **Corrected the Graph scopes to read-only, single-tenant, and actually sufficient** (#231).
  Sign-in requested `Files.Read` + `Files.ReadWrite` + `User.Read` from two places — wrong in
  both directions for this customer: a **write** scope on a deployment meant to be read-only, and
  no `Sites.Read.All`, so site enumeration (`/sharepoint/sites` → Graph `/sites?search=*`) 403'd
  even though the roadmap claimed that scope was requested. Both entry points now import one set
  from a new leaf `sharepointScopes.js` so they cannot drift: `['User.Read', 'Files.Read.All',
  'Sites.Read.All']` — read-only, delegated, admin-consented, and enough to reach team-site
  libraries rather than the user's OneDrive alone.
- Synced the integration roadmap's SharePoint column to the code that already shipped (#221): site
  enumeration, library listing, download, chunked >4 MB upload and original-archiving were marked
  todo while the backend ships them all — the same doc-vs-code drift the backlog carried.
- **Moved the Entra app (client) and tenant ids to runtime `/config`, and added a "Sign in with
  Microsoft" button** (#239). The SharePoint sign-in read its Entra ids from build-time `VITE_AZURE_*`
  baked into the bundle, so pointing ACP at a customer's tenant meant a rebuild. They now come from
  `GET /config` (`ACP_AZURE_CLIENT_ID` / `ACP_AZURE_TENANT_ID`) — the same pattern `google_client_id`
  already uses — with `VITE_AZURE_*` kept only as a local-dev fallback. `SharePoint.jsx`,
  `Integrations.jsx` and the new login button all read through one `getSpAuth()`, so the three
  sign-in paths cannot request a different app; a deployment (or each customer's tenant) is now an
  env var, no rebuild.
- **Made the "Sign in with Microsoft" button actually sign a user in — three fixes, three root
  causes** (#241, #242, #243). #239 shipped the button dead: `index.html` loaded MSAL v3 from
  `alcdn.msauth.net`, which publishes only through v2.38.1 (probed: 2.38.1 → 200, every 3.x → 404),
  so `window.msal` never loaded and every user saw "Microsoft sign-in isn't ready yet — please
  refresh" forever; a green `vite build` cannot catch a runtime script fetch. #241 loads the v3 UMD
  from jsDelivr, pinned to a digest with SRI (a PHI deployment loading third-party auth JS should
  verify the bytes), and a test pins major ≥3 / not-alcdn / SRI present. #242 replaces the fresh
  `new PublicClientApplication()` per click (duplicated in `SignIn.jsx` and `Integrations.jsx`) with
  one `msalClient.js` instance per (clientId, tenant) whose `signInForScopes()` clears a stuck
  `*.interaction.status` lock and retries exactly once — a closed/blocked/double-clicked popup left
  MSAL's `interaction_in_progress` lock set permanently, and "clear your browser storage" is not an
  instruction to give a rollout group. #243 fixes the backend: the access gate only ever verified
  Google tokens, so a Microsoft user was bounced with "session expired" on their first authed call —
  Google worked, Microsoft was cosmetic. New `core.verify_ms_token` asks Graph `/me` (same
  ask-the-provider shape as `verify_gis_token`, cached 9 min) and the gate routes on
  `X-Auth-Provider: microsoft`; the SPA sends the Entra token as the bearer via `setMsToken` (not
  `setGoogleToken`, whose tokeninfo would reject it). Deliberately no audience-pinned check the Google
  lane lacks — tighten one, tighten both.
- **Stopped `/sources` 401'ing a signed-in Microsoft user who has no Google Drive** (#245). Found
  live 2026-08-11 as the last thing standing between a Microsoft user and the app: sign-in and every
  authed call were 200, but `/sources` is Drive-specific and `core.drive_service` raised 401 with no
  `X-Drive-Token` — and the SPA read any 401 as an expired session, bouncing the user to sign-in and
  clearing the bearer, which cascaded a second 401 onto the concurrent `/scans/active`. Having no
  Drive is the normal state of a SharePoint user, not an error: `/sources` now returns `[]` (200) in
  GIS mode with no Drive token; Google users and demo/ADC mode are unchanged.
- **A route-level 401 no longer signs the user out, and sign-in errors read as plain language**
  (#247). The access gate now marks its own 401s with `X-Acp-Auth: session`; `api.js` clears the
  bearer only on that marker, so a route refusing for its own reason surfaces as a normal error with
  the session intact (a 403 allow-list refusal is deliberately unmarked). `authErrors.friendlyAuthError`
  maps the common MSAL/Entra strings — wrong tenant → "use the ACP work account", 700016 → "use another
  account", blocked popup, consent needed — to one actionable sentence, keeping the AADSTS code for an
  admin on anything unrecognised rather than the raw wall; used by both entry points.

## Feature: Operator scan scope · #4601

- Closed the gap where operator scope gated assessment and scoring but **nothing gated
  remediation** (#137). Zero scope references existed across `handlers.py`, `remediate.py`,
  `remediate_office.py`, `remediate_pdf.py`, `proposals.py` and `apply_alt.py`, so a scoped
  scan still wrote changes into a customer's document for criteria they had explicitly
  excluded — and silently, because those diffs were filtered back out of the score. The
  document changed; the report did not say so.
- Extended that gating to the office and PDF fixers (#141).
- Made a scan scope expressible as data rather than only selectable from code (#143).
- Built the admin surface that writes it: a criterion × format grid behind Platform settings
  → Scan scope (#145). **The grid is derived, not typed** — `gen_scope_presets.py` emits
  `SCOPE_UNIVERSE`, every (criterion, format) pair the engine can actually reach a verdict on,
  from `RULE_FORMATS` ∪ `REVIEW_FORMATS`, with html excluded because this configures a
  document engagement. 29 criteria. The panel therefore cannot offer a checkbox that would
  change nothing, and cannot drift into implying capability the engine does not have.
- Fixed the SPA rendering a scope from its bundle rather than the one the server gates on (#138).
- Generated `scopePresets` into both SPAs so the two cannot disagree (#150).
- Fixed a scope grid that was hiding four pairs the engine actually judges (#152).
- **De-identified the customer from the shipped app** (#259). The customer's name reached the SPA
  bundle and the API two ways: personal-name comments, and the `deva-final` scope-preset slug
  (compiled into `scopePresets.js` and stored as the `scan_scope` setting value). Renamed the preset
  to `engagement-14` at its source of truth and regenerated both SPAs; criteria × format contents
  are identical, so no coverage change. Operational note recorded: any environment still persisting
  `scan_scope=deva-final` must be re-set (an unknown preset fails open and shows on `/config`).
- Rendered the shared SC/format scope editor inside the connected Google Drive browse panel,
  collapsed above "Scan selected", persisting to `scan_scope` so the scan inherits it server-side
  (#260). v1 kept byte-identical for the driveArchive parity guard, with a source-level test locking
  that in. Superseded the same day by the wizard below, which retired this Drive-panel copy.
- **Rebuilt scope selection as a wizard with a required confirm-before-scan modal, and redesigned
  the detailed matrix behind it** (#261, #262). Phase 1: a `ScanScopeWizard` (profile picker, format
  cards with live registry counts, summary, collapsed grid) owning its own scope state; "Scan all
  sources" now opens a required scope modal instead of scanning on a scope the operator may never
  have looked at. Phase 2: the grid inside Customize gets a sticky header + criterion column,
  WCAG-principle grouping with group All/None, per-format column and row All/None controls, three
  cell states (Selected / Excluded / Not-supported), and view-only search + filters (text, Selected
  only, Level A/AA, Supported-by-all-formats, fix-mode) — filters never mutate scope, so narrowing the
  view cannot silently change what a scan does. Frontend only; suite green at 1595.
- **Greyed out and disabled the criterion × format cells ACP cannot yet assess** (#268). The matrix
  offered `SCOPE_UNIVERSE` — every pair the engine can *reach* — which is broader than what it can
  *assess*: 12 offered pairs (Keyboard on PPTX, Name/Role/Value on XLSX/PPTX, Non-text Contrast on
  XLSX/PPTX/PDF, Focus Order on PPTX/PDF, …) have no assessment verdict, so a tester could tick them
  and get nothing back. Readiness is keyed on the CI-locked assessment axis (`capability.js`, ADR
  0023): 'auto' or 'review' lane is ready, 'human'/absent is not. Not-ready cells carry no checkbox
  and drop out of selection, presets and every count; 2.1.1 Keyboard and 2.4.3 Focus Order have no
  ready format and render NOT READY. Honest side effects intended: format cards now show assessable
  counts (docx 15, xlsx 11, pptx 11, pdf 12 — down from reachable 15/15/16/15) and Core 17 selects 49
  ready checks, not 61 reachable pairs. A stored scope naming not-ready pairs is projected through
  `readyOnly` on load so it does not read as dirty.
- **Froze each scan's scope — Remediate and score now read the scan's recorded boundary, not the
  live global** (#267, Phase 3a). Assess/coverage were already frozen (they count stored rule
  traces) but the score and the Remediate gate resolved the *live* `active_scope(store)`, so changing
  the operator scope after a scan silently altered what an old scan would remediate and re-scored it
  while its Assess counts stayed put — a Remediate/Assess contradiction. Every per-scan read now goes
  through `scan_runs.scope["scan_scope"]` recorded at scan start, rehydrated by one shared
  `scope_from_json` so score and traces cannot diverge on how the same JSON is read;
  `store.get_scan_scope` fails loud on a corrupt stored scope (never silently widens) and returns
  `None` only for legacy scans, which read as unrestricted everywhere — never the live global, which
  would reintroduce the drift. `rescore_reused` threads it too, a deliberate ADR-0011 reinterpretation
  ("scope in force now" = this run's frozen scope). Run payload projects `scan_scope` additively for the
  3b scope chip.
- **Pre-release backend hardening from the live smoke test** (#266): `is_scope_owner` returned on
  `GET /me` and `/config` so the SPA can render scope read-only for non-owners; `PUT /rubric` gated to
  the owner; Langfuse now logs `completion_chars`, not the AI's text (PHI). Incremental-vs-scope
  behaviour deliberately deferred.
- **Derived the blocking conformance level from the selected scope and dropped the A/AA/AAA
  picker** (#279). The Assess step asked for a WCAG level a second time, after the user had already
  chosen the success criteria in scope — one fact behind two controls that can disagree. The level
  now follows `SCOPE_SCS` (any AAA criterion → AAA, otherwise AA, the legal ADA/EAA/508 floor the
  standard docx scope resolves to); the radio, its `LEVELS` table, `setLevel` and the orphaned
  `reset()` are gone, and the stale "the level controls which SCs count as blocking" explainer is
  replaced by a derived-level line. Conformance computation and every downstream count are unchanged
  (AA → 14 criteria block). Suite green at 1648.

## Feature: v2 frontend redesign · #4602

- Forked the SPA so the redesign can move without risking the live one (#139).
- Gave the fork a CI gate — it shipped with none at all, and the gate had no manual
  trigger (#140).
- Moved scope selection to step 1 of Discover, above the scan controls (#153). The component
  ports byte-for-byte from `frontend/`; **placement is the change.** Behind Platform settings
  it was a rarely-touched platform default, which is the wrong home for a per-engagement
  choice an operator makes every time — an admin screen nobody opens is where a critical step
  goes to be skipped. Open by default only while `files.length === 0`, the pre-discovery state.
- Cut the nav and settings down to what an operator actually uses (#151).
- Made remediation collapse to the one section being worked in (#154).
- Showed the 17 tracked criteria and what each one actually checks (#155), and made the scope
  grid offer those 17 rather than all 29 (#168).
- Said what the numbers are counting, on Remediate and Publish (#164).
- Made the file-type toggles do what the panel already said they did (#166).
- **Shipped the scan-scope editor, which had been merged but never deployed** (#191). The
  file-type and criterion selectors live in `frontend-v2/src/ScanSetup.jsx`, but
  `deploy/public/Dockerfile` copied `frontend/` — v1 — which has neither. The feature was
  merged, wired and covered by rendered-DOM tests while the deployed app still opened on
  "Start here — connect a source & scan". It read as a backlog gap and was a packaging one;
  three separate places name the SPA tree and all three have to agree.
- **Made the scan scope reachable after the first scan** (#192). `ScanSetup` was rendered only
  by `EmptyState`, which appears only before a workspace's first run — so the controls that
  shape every number on the dashboard were reachable exactly once per workspace, and every
  session afterwards opened with no route back to them. This is the gap behind "I still don't
  see where to select the SCs".
- **Stopped a scan running when its scope could not be saved** (#187). `scanAndSave` awaited
  `save()` then called `onScan` unconditionally, and `save()` reports failure into a status
  message rather than throwing — so a rejected write (expired session, 500) started a scan
  against the *previously* stored scope while the screen displayed the operator's new
  selection. Worse than not scanning: the result looks scoped, is not, and nothing on the page
  contradicts it. Found by writing the missing tests rather than by reading the code.
- **Made the file-type filter apply to every tab** (#195, #196). It lived inside Discover as an
  inline `files.filter(...)`, so it applied to the inventory and nothing after it — App handed
  the unfiltered list to Assess, Remediate, Publish, Overview, Monitor and the Knowledge Graph.
  An operator who scoped to .docx got a docx-only inventory and then a full estate on every
  screen that followed: PDFs scored, queued for remediation, counted in totals, and certified
  against. Found by watching a live estate scoped to .docx and finding PDFs in the inventory.
  .docx is now the default.
- Added a launch config for frontend-v2 (#193).
- **Made scan setup lead with a profile, so Step 1 drives Step 2** (#212). The setup flow now
  opens on a document profile and feeds it forward: the scope grid a user sees in Step 2 is shaped
  by the answers in Step 1 rather than presented cold.
- **Synced the v2 capability table to the backend and guarded it against re-drift** (#216). The
  table the redesign renders is now generated from the same source the engine gates on, with a
  CI guard that fails if the two disagree — the recurring "the panel claims capability the engine
  doesn't have" hazard, closed structurally rather than by hand.
- **Made the AI Work Inbox collapsible and searchable** (#232). The inbox stacks a rich
  EvidenceCard per finding, and a real estate produces dozens — navigating them meant scrolling,
  with no way to jump to a file or criterion. Added a search over each item's filename, WCAG
  criterion (number AND name) and AI recommendation text (token-AND, case-insensitive, priority
  order preserved), and per-card collapse plus a collapse-all so the queue reads as a list of
  headers a reviewer opens one at a time. UI-only — nothing touches a decision, cards default to
  expanded. Each card collapses via a native `<details>` (keyboard-operable, self-announcing, no
  `aria-expanded` to drift), the same reasoning the RemSection helper follows — the search logic is
  a pure function so it is unit-tested directly rather than through a mount.
- **Redesigned Integrations into a Sources page, and routed every scan through one New-scan review
  modal** (#263). The tab is now "Sources", the bottom workflow nav there is gone, and Connected /
  Available sources are split into truthful status cards — one dominant health state, read-only
  demoted to a detail, honest "{n} in Drive / {n} in last scan" counts with no fabricated "excluded"
  bucket. Every scan start opens a single review modal (sources + behaviour toggles + estimate + the
  `ScanScopeWizard`), so there is one place a scan's inputs are confirmed. Frontend only; suite green
  at 1610.
- **Put a universal scan gate in front of every scan start** (#264). An App-level `requestScan` wraps
  `doScan`, so Discover, Overview, single-file, Sources and browse all open the review modal before a
  scan begins — no path left that scans without showing what it is about to do. The shared
  `ScanReviewModal` widened to 940px (~1.5×), and the sticky scope-matrix header no longer overlaps
  its rows (`--surface` was undefined → transparent; now aliased to `--card`). Suite green at 1630.
- **Pre-release polish batch from the live smoke test** (#265): scope renders read-only for a
  non-owner (reads `me.is_scope_owner`, fail-open — also fixes a latent `setCanEdit` crash);
  session-scoped scan default; accurate source label; a ~0 time estimate is suppressed rather than
  shown; browse scans don't persist scope; `AssessRunner` literal-ellipsis fix; error-banner prefix.
  Frontend only; vitest 1637/150.
- Swapped the simplified white-cloud OneDrive tile for the official full-colour OneDrive mark on a
  white tile, matching how the Google Drive logo directly above it is rendered (#271). Icon only.
- **Dropped the Coverage-matrix (xlsx) and Method-deck (pptx) deliverable downloads from the
  Platform-settings header** (#275), with their now-dead plumbing (`exportDeliverables` import,
  `dl`/`dlErr` state, `grab()`) and the test that asserted the download-error UI. `exportDeliverables.js`
  itself stays — `pdfReport.js` still imports `statusFor` from it and its two tests still pass. Suite
  green at 1639.

## Feature: Dependency security · #4603

- **Upgraded pdfjs-dist to 6.2.108, closing arbitrary JavaScript execution on opening a
  malicious PDF** (#194, GHSA-hq66-cqwq-w95j, HIGH). Also dompurify ≤3.4.12, where
  `CUSTOM_ELEMENT_HANDLING` bypasses `afterSanitizeElements` and `IN_PLACE` hook removal leaves
  a detached subtree executable (GHSA-c2j3-45gr-mqc4, GHSA-55q2-fjhq-7xh7). Found by
  `npm audit --omit=dev` on both SPAs — **`--omit=dev` is the part that matters**, because these
  are not build tooling: they ship to the browser. A platform whose entire purpose is ingesting
  untrusted documents cannot carry a parse-a-PDF-and-run-JS bug.

## Feature: Alt-text generation and grounding · #4604

- **Made a missing OCR binary say so instead of quietly degrading** (#190). `requirements.txt`
  installs `pytesseract`, which is a *wrapper*; the tesseract binary comes from the Dockerfile,
  so a developer who pip-installs locally has the import and not the engine — and nothing
  errors. What happens instead is worse than an error: an alt is only written inline when it is
  grounded in text read from the image, so with no OCR nothing can be and every 1.1.1 draft
  routes to `proposals` for human approval. That is exactly correct behaviour for an ungrounded
  guess, and indistinguishable from the model being bad. It cost most of 2026-08-08 — DOCX
  remediation was diagnosed as broken, then as a wiring bug, then as model quality, three wrong
  answers in a row, each plausible.
- Added "presents" to `_ALT_LEAD` (#185). The list strips caption-shaped openings from a vision
  draft — "The image shows", "a photo of" — because by the time alt text is read aloud the
  screen reader has already announced it is an image. It held nine verbs and not this one, so
  "The image presents a bar graph…" reached the alt attribute intact. Found by diffing raw model
  output against cleaned output rather than by reading the pattern list.
- **Raised the draft token budget that was silencing every reasoning model** (#198). `suggest_fix`
  capped generation at `num_predict=60`, sized for the answer alone ("under 30 words"). A reasoning
  model spends that budget on its thinking pass and never reaches the answer, so the response comes
  back empty, `if not text: return None` fires, and the card reads "no draft" — indistinguishable
  from a model that cannot do the task. Measured on qwen3:14b: `60` → 0 characters in 2.2s, `400`
  → a correct rewrite in 14.0s. `num_predict` is a ceiling, so raising it costs a non-reasoning
  model nothing (llama3.1:8b answers 2.4.4 in 0.3s). Every prior benchmark of a reasoning model
  against the assisted lanes had been measuring the cap.
- **Deferred alt-text to a human when the vision model returns garbage, not only when it returns
  nothing** (#255). The 2026-08-12 bake-off (qwen2.5vl:7b vs moondream, llama3.2-vision, minicpm-v,
  granite3.2-vision, eight real document images with ground truth) showed moondream — the CPU-deploy
  default — returning empty on some images and non-empty garbage on others ("~~~~~~Moviaio~~~~~~"
  for a logo, "!!!Readings #1!" for a scatter plot). `describe_image` already deferred an empty reply;
  garbage slipped through and became the alt text in a compliance artifact. New `_is_usable_alt`
  requires a floor of real alphabetic content (min length, alphabetic majority, ≥2 content words) or
  the draft is treated as nothing usable and routed to a human — model-agnostic, so it holds whether
  the deploy runs moondream or qwen2.5vl once the GPU lane lands (qwen scored ~97% and needs no
  guarding; the floor costs a good model nothing). Tests cover the exact bake-off garbage.
- **Gave the RunPod serverless vision lane a cold-start timeout, and stopped hiding the GPU miss**
  (#286). R12 found GPU vision never engages in prod — alt-text falls back to the local CPU floor and
  the cost panel reads "local, zero cloud" — and the failure was invisible without `az`. Two fixes:
  `_vision_generate` called the scale-to-zero VL-7B provider with `OLLAMA_VISION_TIMEOUT` (120s), which a
  first-call GPU boot + model load routinely exceeds, timing out into a silent local fallback — a
  healthy endpoint read as broken; the serverless provider now gets `RUNPOD_VISION_TIMEOUT` (default
  240s, env-tunable), the local path keeps 120s. And on a GPU failure the local fallback overwrote `res`,
  so only the local row reached `ai_calls` — the failed cloud attempt lived only in worker stdout, which
  is why "local 8/8" was inconclusive; the failed attempt is now its own `ai_calls` row (`zone=cloud`,
  `ok=False`, with `providers.REASON_*`), so the miss and its reason show in the audit trail / cost
  panel. Makes the remaining root cause (rotated key R3, or the worker env value) diagnosable from the UI
  after deploy. 1.1.1 stays "assisted"; no capability change.

## Feature: Test corpus and CI · #4605

- **Gave the corpus manifest actual expectations** (#188). `test-corpus/manifest.json` now
  carries `expected_rule_ids` from the generator that calls itself an oracle; the file it
  replaced was a descriptive index (file/size_kb/desc) with no expectations in it at all, so
  nothing measured whether any detector is correct.
- Reconciled two generators that write that file and disagree about field names — one emits
  `desc`, the other `notes`, and the reader accepted only `desc`, in two places, while sitting
  in neither CI workflow. Regenerating the oracle would therefore have matched zero fixtures and
  rendered every `rules/*/README.md` without its fixture list, **silently**. Both readers now
  accept either; making one generator authoritative is left as a decision.
- **Parallelised the backend suite, cutting 77s of a 118s job** (#189) — measured at 47.9s
  serial against 15.5s with `-n auto`. The backend job was the entire critical path; the two
  frontend jobs run alongside it and finish sooner, so nothing else was worth touching.
  `--dist loadfile` is a correctness requirement rather than a tuning knob: one test deliberately
  corrupts the real generated `scopePresets.js` and restores it in a `finally`, which is the
  right test to have but is flaky under plain `-n` without file-level distribution.
- **Turned the labelled corpus into a CI gate** (#200) — the oracle expectations from #188 now run
  as a check on every push, rather than a script somebody remembered to run. Detector regressions
  surface at PR time instead of on a customer document.
- **Sampled each criterion's boundary densely, bounded by its own n** (#207). Fixtures now cluster
  where a detector's decision flips (the pass/fail edge) and size the sample per criterion rather
  than uniformly, so a criterion with a subtle boundary gets the coverage it needs and a simple one
  is not padded.
- **Retired the redundant Azure Pipelines CI's auto-triggers** (#235). `azure-pipelines.yml` is a
  byte-for-byte mirror of `.github/workflows/ci.yml`, which GitHub Actions already runs on every PR
  and push. The Azure org has one parallel job, and two pipelines fed by that file (`acp-ci-github`,
  `jeremyyuAWS.acp`) both triggered on every PR/push, serialising through the single slot — runs sat
  in `notStarted` ~50 minutes, so every PR read `UNSTABLE` on two checks that gate nothing (main is
  not branch-protected). Set `trigger: none` / `pr: none` rather than deleting the blocks (an absent
  trigger in Azure defaults to CI on every branch — the opposite of retiring it); the pipeline stays
  runnable on demand. The repo change proved itself on its own PR: Azure read `pr: none` from the
  branch and skipped it, so the PR merged `CLEAN`. Fully stopping the two pipelines needs an Azure
  DevOps-side disable/delete, which a commit cannot reach — recorded as an open item.
- **Made the Progress Log generator accept an `html` capability change in the WCAG trailer**
  (#257, closes #52). `gen_progress_log.FORMATS` omitted `html`, so a commit declaring `WCAG: 1.3.1
  (html)` with a real Matrix-Note failed format validation and its Progress Log entry was silently
  skipped — while html is a real ACP engine (#37, #41 already wrote `(html)` trailers) and the sibling
  `gen_todo_status` already listed all five formats. An omitted format list now means all five.
  Deliberately *not* changed: `gen_matrix_coverage` stays four formats — the matrix has no html column
  by design (document-format only), so html is read and discarded there; only the log needed it.
- **An adversarial large/malformed corpus generator and a robustness smoke-test spec** (#284).
  `scripts/robustness_corpus.py` builds ~14 files to stress ACP's known bounds — the OCR 30-image cap,
  the vision 25-figure cap, the PDF reading-order 20-page sample, the .NET 180s CLI timeout, the
  job-queue lease — with a manifest of each file's expected Discovery bucket, counted defects, the caps
  it should trip and the assertions: big PDFs (120p text, 100p scanned, 50 images), big Office
  (100-slide pptx, 30-sheet/100k-cell xlsx, 150p image+table docx, 500 tiny images), and edge cases
  (password-protected, truncated, zero-byte, wrong-extension, empty workbook, non-document image, clean
  control). Verified end-to-end (encrypted PDF genuinely encrypted, truncated PDF fails to parse,
  buckets reconcile). `docs/robustness-smoke-test.md` is the checklist — robustness, not accuracy: no
  crash/hang, counts reconcile, truncation surfaced, timeout → uncertain-not-fake-pass, unreadable ≠
  passing. Generator libs are wheel-only test tooling, kept out of `api/requirements.txt`.
- **A complex multi-issue corpus — one file per format with 50+ injected issues across the WCAG SCs
  ACP assesses** (#287), the coverage/accuracy counterpart to the robustness corpus. Verified: docx 59
  issues/10 SCs, xlsx 62/9, pptx 62/7, pdf 59/9, all opening cleanly (52 paras / 6 sheets / 13 slides /
  16 pages), ~13 distinct SCs across the corpus, with a manifest mapping each file to its injected
  {SC: count}. Honest by construction: SCs these libraries cannot author (a real AcroForm control for
  4.1.2, a slide animation for 2.1.1, autoplay audio for 1.4.2, a true colour-only PDF link for 1.4.1)
  are listed per file under `not_seeded` with the reason, so the manifest never claims coverage it did
  not produce.
- **Sharded the backend suite across four free runners** (#321). The ~9-minute backend job (2800+ tests +
  the four matrix/todo/progress-log guards) was the long pole on every PR; splitting it across four
  standard GitHub-hosted runners cuts wall-clock at no added cost (free-tier runners, not larger paid
  ones). Another session's change, recorded here since it landed on `main` in this window.

## Feature: Remediation reaching the file · #4606

- Built `api/apply_text_values.py`, the write-back that never existed for the two text-span
  criteria (#146): an approved 1.3.3 sensory rewrite or 3.1.2 language mark now reaches the
  file across Word, PowerPoint, and — for 1.3.3 — Excel.
- Made `detect_language_parts` marking-aware in the same pass. A round trip through the real
  detector showed 3.1.2 still firing after a correct write, because the detector read extracted
  text and nothing else; a passage marked as the language it *is* now stops counting, so the
  approval can earn credit.
- Fixed two applier bugs of the same shape that the round trip exposed: it marked only the
  60-character locator rather than the whole passage, and stopped at the first match rather
  than fixing every occurrence.
- Made docx 4.1.2 key on the Title that assistive tech actually announces, with approvals
  reaching the file (#144).
- Stopped the docx pseudo-heading promoter building a heading outline out of a large-print
  document's body (#170). It asked one question — is this text ≥14pt — under an assumption its
  own constant records: "body text is ~22 (11pt)". Set the body at 14pt or 16pt and every short
  paragraph clears the floor, so the promoter wrote `w:pStyle` unattended across all of them and
  a document whose structure was fine came back restructured. Nothing on screen said so, and the
  exposed population is documents already enlarged for low vision — the readers this product
  exists for.
- **Correction: the live "Couldn't remediate this file" Drive write-back bug was verified stale, and
  the residual token-expiry path pinned by test** (#258). Roadmap item #1 (est. ~2–3.5 person-days)
  diagnosed a missing write scope and a Blob fallback that did not catch the failure. Neither holds:
  `DRIVE_SCOPES` grants `drive.file`; the Blob copy is written first and unconditionally
  (`handlers.py:617`, ADR 0010) and the Drive-mirror 403 is caught (`handlers.py:679`), so a write-back
  denial never fails the job; the message only fires on a genuine job error; live `acp-worker` logs
  show the mirror succeeding with zero failure signatures. The one real residual — an expired GIS
  token before a queued job runs — was already mitigated (the token rides the durable job payload,
  `handlers.py:448`); new `tests/test_remediate_token_resolution.py` pins that the payload token is
  used when the in-memory store is wiped and that total absence fails cleanly with the honest
  "re-trigger" message, never a partial write. `docs/TODO.md` item #1 struck with the evidence and the
  "engineering left ≈ 2–3.5 person-days" summary corrected to ≈ near zero.

## Feature: Assessment correctness · #4607

- Fixed a clean Word file reporting NOT_EVALUATED — "we did not look" — for 4.1.2 (#149).
  #144 had put docx 4.1.2 into `RULE_FORMATS`, so a *failing* document reported FAIL correctly
  while a *clean* one fell through, the mirror image of the original false-PASS bug. It is now
  registry-backed at `coverage=PARTIAL`, so a clean file reads REVIEW: we checked what our
  technique reaches, a human confirms the rest. PARTIAL rather than FULL because the check reads
  interactive content controls and is silent on ActiveX. Third criterion to make this move,
  after PDF 4.1.2 and 2.4.3.
- Reclassified xlsx 3.1.2 as explain-only (#147) — a proposal nobody can write is not an
  assisted lane.
- Made a squash publish every Matrix-Note it squashed, not just the first one (#148).
- Made the certification PDF meet the standard it certifies (#135, raised by **UTSW**). A
  customer asked whether our report exports are themselves accessible; running ACP's own
  vendored PDF rules over a `build_report` output answered it with three failures — no tagged
  structure tree (1.3.1, critical), `DisplayDocTitle` unset (2.4.2), and no catalog `/Lang`
  (3.1.1, serious). Two were a catalog write that had simply never been made, and are closed
  here. `/Lang` is a module constant because it describes the report's own English prose, not
  the language of the estate being reported on.
- Fixed a simulated settings write reporting itself as a real save (#127).
- **Stopped tracked deletions leaking into extracted text** (#215). Text extraction was reading
  `<w:del>` runs — content the author had deleted under tracked changes — so struck-through text
  fed the detectors and could be judged, counted and even quoted back in a finding. Extraction now
  drops deleted runs, so the checks see the document as it reads, not as it was.
- **Surfaced a .docx with an unreadable body instead of reporting it nearly-clean** (#246). Found by
  edge-case testing 2026-08-11: a .docx whose `word/document.xml` is missing or malformed still opens
  as a zip and still yields `docProps/core.xml`, so the office CLI reported whatever metadata findings
  it could (typically a lone "no document title") and no error, landing the file as a nearly-clean
  `uncertain` — "almost fine, missing a title" when the entire body could not be read. Every docx
  detector self-gates to silence on an unreadable part (the deliberate one-bad-part-must-not-kill-
  the-assessment posture), so nothing affirmatively flagged it. `_docx_body_readable` +
  `_flag_unreadable_docx` now append an explicit engine error ("main content could not be read; the
  file may be corrupt, incomplete, or password-protected") through the same errors channel a CLI abort
  uses, so the file stays non-certifiable with a reason. A non-zip (zero-byte, truncated, renamed .txt,
  encrypted) is left to the existing engine-error path rather than double-reported. Verified on the
  edge corpus: 07-malformed-xml and 08-missing-document-xml flagged; good, tracked-changes, empty and
  unicode/RTL controls not.

## Feature: Multi-tenancy and the control plane · #4608

- Gave `documents` its own tenant column, separate from the business owner (#159). The table
  was not missing a tenant — `save_scan` and `handlers` were both landing one in `owner`. But
  `owner` is ADR 0003's document-*governance* column, sitting beside `department`,
  `business_criticality` and `regulatory_tags`: facts about the customer's document, not about
  which tenant owns the record. A "filter the estate by department" view has to be built on
  `documents`, since it is the only table carrying `department`.
- Added tenant-scoped estate aggregates for the control plane (#160).
- Built an estate view for a single tenant, and a Settings tab to read it (#165).

## Feature: Local model benchmarking · #4609

- Added an ollama service to the local compose stack on a named volume rather than a baked
  image (#161), to find out whether a larger local model does better on the .docx surfaces ACP
  already drafts with. This is deliberately the opposite of `deploy/ollama/Dockerfile`, which
  bakes llama3.1:8b + moondream so a cloud container has no multi-GB cold start — that image
  exists because llava:7b + llama came to ~9.2GB and OOM-killed the container against an 8Gi
  Azure Consumption ceiling. Deployment and local development have opposite constraints.
- Fixed an ollama healthcheck that called a binary the image does not contain (#162).

## Documentation

- PRD for the v2 redesign, written from the requirements list (#163).
- Recorded that pytest is not the backend CI job — three guards run after it (#142).
- **A capability report stating what a green scan actually certifies** (#186). Every fact was
  derivable already and none were readable in one place: `assessment_policy` knows which pairs
  are in the Core 17 and what a clean file resolves to, `remediation_capability` knows the lane,
  `corpus_expectations` knows which verdicts a pair is allowed to reach. Answering the question
  meant joining three tables by hand, which is how it ends up stated as a percentage nobody can
  defend. Two findings fell out of the data rather than review — **17 of 61 pairs can certify a
  PASS and 44 cannot, by design**, a `REVIEW_FORMATS` pair resolving to REVIEW when its detector
  fires and NOT_EVALUATED when it does not.
- Regenerated the capability matrix, and guarded the page that claimed it was guarded (#136).
- **ADR 0030 — the auto-apply gate, granted per criterion by verification completeness** (#201):
  a fix writes itself into the document only where a re-scan can prove it landed, not everywhere a
  proposal exists.
- **ADR 0031 — certification is gated by coverage, not confidence** (#218): a criterion certifies
  a PASS only on formats where the technique demonstrably reaches a verdict, which is what the
  capability registry enforces.
- **Restated what an ACP report is** (#204): it reports what it checked, changed and verified — it
  does not certify. The wording matters to a hospital reading the export.
- Synced the backlog to reality twice — six entries had gone stale in two days (#211), and Phase 5
  marked P5.1/P5.2/P5.5 done with P5.3/P5.4 blocked on installs (#217).
- Recorded that Chain B is automatic now, with the backlog capturing the 21 PRs that landed that
  day (#225).
- **Recorded the 2026-08-12 vision-model bake-off and the alt-text usability guard** (#256): why
  qwen2.5vl:7b is the vision model (~97% vs minicpm-v 59%, granite3.2-vision 47%, moondream 19%,
  llama3.2-vision DNF on eight document images with ground truth), why moondream is not relied on
  for alt text, and what `_is_usable_alt` (#255) does. Written so the decision is not re-litigated.
- **A detailed, file:line-grounded system architecture reference** (#269) complementing the slide
  deck (dated 2026-07-29, pre-Actions-deploy / pre-RunPod-serverless, and stale — it still shows
  `acp-redis` and `acp-ollama` as Container Apps). Ten Mermaid diagrams: component topology
  (acp-app / acp-worker / Postgres / Redis / Blob / RunPod / Grafana), the two-shape worker model
  (in-process threads vs the split `acp-worker` tier), the durable Postgres job queue (jobs schema,
  `claim_job` compare-and-swap — not `SKIP LOCKED` — lifecycle, jittered backoff, sweeper, all 8 job
  types, fan-out vs monolithic), the Discover→Assess→Remediate→Review→Release→Monitor lifecycle (ADR
  0020), the ~25-table data model, the three document engines, the two-axis capability matrix (ADR
  0023), the AI lanes (RunPod serverless Qwen2.5-VL with CPU floor fallback), auth/multi-tenancy,
  build & deploy.
- **Backlog Phase R — 13 pilot-readiness gaps ahead of the 3-user pilot** (#270), in the backlog's
  evidence-named, status-key convention; each item names what to re-run. Capability counts are
  source-verified, not fixture-run (that gap is R10 itself). Summarised under Open items.
- **Backlog Phase W — nine workflow-completeness gaps from walking the end-to-end flow** (#274).
  Observed from the connected-source→governed-content flow drawn as a diagram, *not* confirmed in
  source this session — each names the file to confirm in first, and the header flags them as distinct
  from the code-verified Phase R items. Summarised under Open items.
- **Backlog correction: R12 verified FAILING in prod, R2 downgraded — RunPod GPU vision is not
  engaged** (#276). A live end-to-end drive of `acp-app` on 2026.8.14.1: a real 1.1.1 alt-text draft
  falls back to a local filename-guess template ("this text model cannot see the image") and the
  AI-cost processing-zone counter reads local 8/8 with zero cloud calls — before *and* after clearing
  the `ai_base_url`/`ai_vision_model` override, so the override was not the cause. R2: env *is* set on
  `acp-app` (`az containerapp show`) but the runtime still lands on local, so
  `active_vision_provider()` is not selecting RunPod — most likely the `runpod-api-key` secret not
  resolving at runtime (ties to R3); downgraded to in-progress with the `az` secret-list re-check
  steps. R12 moved from "unverified" to verified failing, with the objective re-test recorded (force a
  1.1.1 draft, re-read the AI-cost zone; a real GPU call must show cloud + an image-derived draft).
- **File-grounded engine architecture references for PDF and for Office + HTML, plus a
  multimedia-captioning LOE** (#280, #282). `docs/pdf-assessment-remediation.md`: the three PDF
  detection layers (vendored `engine/pdf-analyser`, `office_structure` measurement checks, `ocr.py`),
  the in-process (not subprocess) invocation, the auto/assisted/human split, the 1.4.3 contrast fixer +
  the dark-theme incident, OCR grounding, capability declarations and gaps. The Office/HTML companion:
  the .NET analyser (`engine/office-analysers`, DocumentFormat.OpenXml 3.5.1, net10.0; docx 9 / pptx 9
  / xlsx 11 rules) and how `scanner._analyse_office` shells out; first-party Python Office checks;
  `remediate_office.py` as raw OOXML (zipfile + lxml + regex, no python-docx/pptx/openpyxl) with pptx
  2.1.1 and xlsx 3.1.2 the only intentional human-only lanes; and the fact that two HTML analysers exist
  — the control-plane lxml one the scanner uses, and a separate axe-core@4.9.1 + Playwright engine it
  does *not* wire. `docs/loe-multimedia-captioning.md`: current state read from code (HTML `<track>`
  detection only, 1.2.x human-only, no ASR pipeline); Phase 1 transcripts + captions (1.2.1/1.2.2)
  ~10–14 pw, Phase 2 audio description (1.2.3) +8–16 pw; flags the GPU dependency (R2/R12) and the
  PHI-driven local-ASR constraint.
- **A shareable pilot scope & limitations one-pager** (#281) bounding the 3-user SharePoint pilot:
  DOCX-led (full remediation) vs PDF/XLSX/PPTX assess-only, image alt-text human-reviewed (GPU vision
  pending), no multimedia, English only, PHI stays local, no source write-back, ≤25 pages, one library
  / staggered scans — each limit traced to its backlog item (R2/R3/R12, R8, R11, R5/W9) plus a pre-pilot
  checklist.
- **Discovery & triage spec — buckets, ROT triggers, signal availability, re-activation triggers**
  (#283). Every file sorted into one reconciling bucket (assessable / already-archived / ROT /
  filtered-by-type / unreadable) *before* assessment so remediation scope holds only files worth
  certifying. Top recommendation: recognise and honour the customer's existing archive convention (the
  17,512 files renamed `*_ARCHIVED` with "Archived on" metadata) so ACP never re-processes dispositioned
  content. Plus the Redundant/Obsolete/Trivial trigger set, a matrix of what the read-only Graph scopes
  expose vs need enabling, guardrails (recommendation not deletion, legal-hold exempt, explainable,
  confidence tiers), and a code-grounded have-vs-need: the disposition engine and age/modifiedTime are
  real, and modified-after-archive re-activation is already detectable via the source-staleness baseline
  (#253); `_ARCHIVED` recognition, content-hash dedup, real version-supersession, views/access and sharing
  signals are unbuilt.
- **SharePoint support gaps mapped against the UTSW/MOV pilot SOW** (#285) — up to 30 SharePoint
  locations, full scan, folder/date/user archival rules flagging-only, daily monitoring, MS SSO single
  tenant — verified in `scanner.py` + `disposition.py`: site/library enumeration and one-site-per-scan
  today (multi-site orchestration is the biggest gap); folder path is read but the disposition engine has
  no folder match field (small build); native SharePoint column *write* needs `Sites.Manage.All` +
  provisioning (out of scope by design — the pilot is flagging-only, ACP flags internally); reads of
  native metadata (listItem/fields) as rule inputs are a bounded build within the read-only scopes.
  Flags that image alt-text needs the vision model (R2/R12), not the downloaded Llama.
- **The three-denominator model — the product spec behind the estate coverage view** (#297): three
  distinct denominators (discovered / assessment-eligible / remediation-eligible), the capability-status
  taxonomy, the nine-stage funnel, the format × capability coverage matrix grounded in
  `remediation_capability`, how discovery works at scale (whole-estate listing, `FANOUT_MAX_FILES`, honest
  truncation, dedup-by-identity), the scan-setup UX split, and the shipped/next roadmap. Central rule:
  unsupported means NOT EVALUATED, never passed; never report the three as one percentage. Implemented
  under the "Estate coverage" Feature below.

## Feature: docx Core-17 criterion coverage · #4610

Closing the last .docx accessibility criteria that had no lane, so a Word document can be judged on
the full Core-17 rather than a subset. Each is declared with the honest lane it can support.

- **Declared 1.4.1 (Use of Color) and 1.4.11 (Non-text Contrast), then made both assisted** (#202,
  #203). They had detectors but no guided lane; #203 gives each a prefilled card a reviewer elects
  with one click (the shade that reaches 3:1 is computed, not guessed), moving them from "human"
  to "assisted".
- **Declared 2.1.2 (No Keyboard Trap) — the last Core-17 criterion with no .docx lane** (#206).
- **Declared docx 4.1.2 (Name, Role, Value), which was already being fixed deterministically** but
  had no lane recording it (#208).
- **Fixed 1.1.1 failing to read the decorative marker ACP itself writes**, and added a labelled
  capability benchmark alongside (#199) — the detector could not see its own output, so a correctly
  marked decorative image still flagged.
- **Caught three detectors that were silently Word-only** (#205), by asking the suite the question
  rather than reading the code — each ran on .docx and quietly did nothing on the other office
  formats it was assumed to cover.

## Feature: docx running header/footer parity · #4611

The recurring blind spot that a content check reads `word/document.xml` alone while the same defect
lives in a running header, footer or note — where clinical documents routinely put banners, rule
lines and Patient-ID fields. Each fix walks the body plus the header/footer/note parts through the
shared `_docx_story_xmls` helper, so the checks cannot drift on which parts count.

- **2.4.4 Link Purpose** now judged in headers, footers and notes, not just the body (#214).
- **3.1.2 Language of Parts** reads a header's language mark where the header's text is read (#226).
- **1.4.1 Use of Color** sees a colour-only link in a footer, not only in the body (#227).
- **2.1.2 / 3.3.2 / 4.1.2 — form controls in a header are judged like the body's** (#229). A
  content control or legacy form field in a running header is as interactive, as trap-prone and as
  label-dependent as one in the body; three checks missed every one. Consolidated onto one helper
  so the 2.1.2, 3.3.2 and delegated 4.1.2 reads can never disagree about which controls count.
- **1.4.11 Non-text Contrast — a faint-outline shape in a header/footer** now raises, not only in
  the body (#230). Reproduced with a fixture first; the detector still reports only the single
  worst shape, so widening the scan cannot multiply findings, and it stays a Review lane that
  defers the decorative call to a human.

## Feature: Capability registry (ADR 0031) · #4612

- **Migrated docx 1.1.1, 2.4.4 and 3.1.2 onto the registry's coverage gate** (#219), retiring the
  older `store.RULE_FORMATS` + `_certify` path they reached REVIEW through. The two mechanisms
  agreed only by coincidence of values — the "disagreeing tables" hazard the registry exists to
  end. **Verdict-neutral by construction**: measured before and after across every finding-state,
  each criterion still resolves clean → REVIEW, blocking → FAIL, advisory → REVIEW; only the code
  path producing REVIEW moved, pinned by a new migration test so a future edit cannot silently
  reclassify on the most consequential path ACP has.
- **Pinned the "a detector never fails a scan" contract** (#224, #228). `rule_registry.assess` calls
  every detector as `reg.detector(path) or []` with no try/except, so a detector that raises on a
  corrupt upload takes down the whole assessment of that file, not one criterion — and a hand-forged
  or truncated .docx is exactly what a real user uploads. #224 fed the three migrated docx detectors
  a battery of broken packages (not a zip, empty zip, document.xml truncated mid-tag, an rId with no
  rels, a missing image Target); #228 widened it to the whole registry via `all_registrations()`, so
  a detector added later is covered the day it registers, with a floor assertion (≥11 detectors)
  guarding against the imports silently ceasing to register. All 11 pass as shipped — the value is
  the ratchet, not a fix.
- **Declared xlsx 1.4.1 / 1.4.11 / 4.1.2 and pdf 2.4.3 — four shipping detectors moved off "not
  evaluated", behind a named emit-proof gate** (#288, #289; backlog R8 + R10). Four capability cells
  had shipping, emit-proven detectors yet read N/A on the matrix because the registry never declared
  them. The honesty rule is that a cell is declared only once a test proves its detector *emits* on a
  targeted fixture; those proofs existed but were scattered, so #288 consolidates them into one named
  R10 declare-gate (`office_color_only_checks` → XLSX_COLOR_ONLY_STATUS, `xlsx_nontext_contrast_checks`
  → XLSX_NONTEXT_LOW_CONTRAST, `office_control_review_checks` → 4.1.2, `pdf_focus_order_checks` →
  PDF_TAB_ORDER_NOT_STRUCTURE) that also guards the four cells against a future refactor silently
  breaking a declared detector. #289 then declares them: xlsx 1.4.1 and 4.1.2 registered
  (PARTIAL/MEDIUM; 4.1.2 requires nothing — BASELINE lists FORMS for docx/pdf and not xlsx on purpose,
  and the detector confirms it by reporting a control whose name/role it *cannot* read, self-gating to
  `[]`), xlsx 1.4.11's human remediation lane completed alongside its registration, pdf 2.4.3 with auto
  remediation (`/Tabs = /S`) but a *review* assessment override — a deterministic `/Tabs` write is a
  proxy for tab order, not proof. `REVIEW_FORMATS` drops xlsx from 1.4.1/4.1.2/1.4.11 so the registry
  branch (clean → REVIEW) owns the verdict instead of the review lane shadowing it to NOT_EVALUATED — the
  same lesson the docx 4.1.2 migration recorded. Frontend `capability.js` (both trees) synced; matrix
  regenerated (XLSX 14→15, PDF 15→16 review cells; wizard counts xlsx 11→14, pdf 12→13; 2.4.3 leaves
  the fully-not-ready set, 2.1.1 remains the lone example) — values computed from the tables, not
  hand-typed. Honest note: frontend vitest was not runnable locally for #289 (no runner in that env);
  the Python assess-coverage contract guard reimplements the JS rollup and passed, and CI vitest
  surfaced and then confirmed the pinned-count fallout.

## Feature: PHI privacy and document access control · #4613

Work specific to a hospital deployment where the documents are patient health information — what
leaks into a trace, and who can reach a remediated file.

- **A reviewer's note now leaves the system as a length, not as text** (#210) — the note body was
  reaching an observability trace verbatim; only its length does now.
- **A filename that names a patient now travels as a label, not the raw name** (#213). Filenames in
  this estate are PHI, so traces carry a stable label instead of the name itself.
- **Closed a cross-owner disclosure on the remediated-file route** (#209). `GET
  /scans/{scan_id}/files/{filename}/remediated` read the remediation URLs with no owner predicate;
  the blob download was correctly owner-scoped and returned `None` for a foreign document, and that
  `None` fell through to a Drive mirror URL taken from a row the caller had no right to — a correct
  control creating the path to an incorrect one. Found by re-checking the two routes the
  2026-08-08 owner-derivation audit had listed as not covered.

## Feature: Continuous deployment to Azure · #4614

The live app had sat on the 2026-08-08 build while `main` moved on; this makes a merge to `main`
reach production, safely.

- **Deploy on merge to `main`** (#221), gated by the production GitHub Environment (required
  reviewers) rather than by keeping the trigger manual — a deliberate, eyes-open choice, with the
  manual dispatch still available to pin a sha or run blue-green.
- **Trigger after CI passes on `main`, not on the push that races it** (#222), so a deploy never
  ships a commit its own checks haven't cleared.
- **Restored single-revision mode so a normal deploy's new revision takes traffic** (#223).
- **Made the Google ADC optional when GIS per-user sign-in is configured** (#220), so a
  per-user-auth deployment doesn't require an application default credential it never uses.
- **Resolved `main` at approval time, not at the frozen trigger sha** (#238). The auto-deploy
  (`workflow_run` after CI) pinned `github.event.workflow_run.head_sha` — frozen when `workflow_run`
  fired — so with the production environment's required-reviewer gate, approving a deploy that had
  waited hours shipped that stale sha while newer merged commits sat unshipped. That is exactly the
  deploy drift the production monitor exists to catch, reintroduced by the deployer itself. Checkout
  now uses the branch ref (`inputs.pin || 'main'`), resolved when the step runs — after the wait.
- **Stopped the production monitor false-flagging a CI-only file as deploy drift** (#237). The
  deploy-drift check counted the root-level `azure-pipelines.yml` as image-affecting — the `.github/`
  cosmetic-denylist prefix never reaches a root file, and no `COPY` in the Dockerfile ships it — so
  #235's `d9b5f14` (which touched only that file) produced a false red naming a CI-only change as
  "what production runs". Exempted by name rather than by a broad root-`.yml` rule, so a future root
  yaml that *does* ship still counts.
- **Disabled the two redundant Azure Pipelines in Azure DevOps** (ops, no commit) — completing the
  #235 retirement. `acp-ci-github` (id 12) and `jeremyyuAWS.acp` (id 13), both GitHub-sourced against
  `jeremyyuAWS/acp`, were set `queueStatus: disabled` via the Build Definitions API, so they no
  longer post the ~50-minute `UNSTABLE` checks on every PR. `acp-ci` (id 10) was deliberately left
  enabled: its source is an Azure Repos (TfsGit) `acp` repo on branch `fix/hitl-auto-verify`, not the
  GitHub repo, so it never posted GitHub checks.
- **Made the SPA revalidate `index.html` so a deploy cannot strand clients on stale JS** (#244).
  Plain `StaticFiles` sent an ETag but no `Cache-Control`, so a browser could serve a cached
  `index.html` without re-checking and keep loading the *old* content-hashed bundle it named. That is
  what happened on 2026-08-10: after the Microsoft-auth fix (#243) landed, a signed-in Microsoft user
  stayed on pre-fix JS that never sent `X-Auth-Provider`, so every request 401'd against a backend that
  could by then authenticate them; only a manual hard-refresh cleared it — untenable for a team
  rollout. `SpaStaticFiles` now sets `Cache-Control: no-cache` on text/html (a cheap 304 via the
  existing ETag when unchanged) and `public, max-age=31536000, immutable` on `/assets/*` (safe: a new
  build is a new filename). Pinned by `tests/test_spa_cache_headers.py`.
- **Root cause of the vision lane never running in production**: the `ollama/ollama` base
  image declares `VOLUME /root/.ollama`, so under ACA's empty volume mount the models baked
  into that path were shadowed — a ~13 GB push booted with an empty model list and vision
  silently fell back to a template. Models now bake to and serve from `/models`
  (`OLLAMA_MODELS`), a non-volume path; build hardened with `set -e`, the error-swallowing
  `wait … || true` dropped so a failed pull fails the build, and `ollama list` /
  `test -d /models/manifests` asserted. Applies to GPU (llava:13b + llama3.1:8b) and CPU
  (moondream + llama3.1:8b) images (#302).

## Feature: Release Center · #4599

The Publish tab presented itself as a conformance report — an estate score, a "certifiable" queue,
"Original preserved" — language ACP's automated checks cannot back: they verify the criteria in scope,
not overall WCAG conformance. This turns it into a controlled-release surface that claims only what
the write path actually does, and tells a reviewer when the source moved on under a fix.

- **Renamed Publish → Release Center and removed every claim ACP cannot prove; then made release a
  confirmed, policy-visible act** (#249, #252). Phase 1 (labels/copy/layout only, no behaviour change):
  nav "Publish · certify" → "Release · approve & deploy"; the 42px estate score and four-counter row
  are gone, replaced by "X of Y documents were automatically verified within the selected scope … ACP
  verifies the criteria in scope — it does not certify overall conformance"; "certifiable" → "verified
  in scope"; "Original preserved" → "Original untouched · the fixed copy is written to a separate
  'remediated' folder — the source file is never overwritten" (a claim the Blob write path actually
  backs); the conformance PDF demoted to a secondary "Evidence & reports" link. Phase 2: an honest
  release-policy *panel* (not a selector for a behaviour the backend lacks — `POST /publish` only ever
  writes a corrected copy; replace-in-place is roadmap) that reads the real `GET /settings` and states
  where a copy lands ("remediated copy → Drive '<folder>' + Blob", or Blob alone), with a "Why can't I
  replace the original?" explainer that says plainly it is not built and SharePoint is read-only; a
  confirmation modal before Release / Release-all stating the checkable consequences (destination,
  originals never overwritten, the audit entry, *not* a conformance certificate); a per-row destination
  chip. The honesty-critical copy lives in a pure `releasePolicy.js` so tests can assert the confirm
  lines never say "certify".
- **Warned the reviewer when a source changed in Drive since the scan — baseline, endpoint, and
  surface** (#253, #254; Phase 3). Backend (#253): `provenance.DRIVE_FIELDS` gains `modifiedTime` (one
  edit reaching all three `files().list()` masks); the scanner carries `source_modified` through both
  persistence paths (fan-out and in-process `run_scan`) into a new nullable `file_records.source_modified`
  column (additive migration, written at both INSERT sites, refreshed on re-scan via `EXCLUDED`) —
  NULL for pre-existing scans and non-Drive files, which read downstream as "untracked", never
  "unchanged". Native Docs/Sheets/Slides have no md5 but do carry `modifiedTime`, so they are tracked
  too. New owner-scoped `GET /scans/{sid}/source-status` fetches each tracked file's current
  `modifiedTime` with the caller's read-only creds and classifies via a pure `api/source_staleness.py`
  (RFC3339 parse + classify; a precision-only diff is not a change): 'stale' / 'unchanged' / 'untracked'
  / 'unavailable' (a per-file 404/403/parse failure never fails the batch). UI (#254): `Publish.jsx`
  fetches it on mount; a red banner appears *only* when something changed — "⚠ N documents changed at
  the source in Drive since this scan — re-scan before releasing" — with "↻ Re-scan changed sources (N)"
  looping `rescoreFile` over only the stale files (honest: it kicks off the re-scan, it does not block on
  the worker). Per-row badges show 'stale' and 'unreachable'; 'untracked'/'unchanged' render nothing, so
  the UI never claims a file is unchanged it could not verify.
- **A real source-drift panel on the Monitor tab** (#278; closes backlog R5). Continuous Monitoring
  showed only illustrative drift (`sourceWatch` from `sim.js`); the real per-file source-staleness the
  Release Center already gates on (`getSourceStatus`, #253) never reached Monitor. A "Source drift ·
  LIVE" panel now fetches it, derives the stale set from the *server* state, and shows how many files
  changed at the source since the scan, the changed filenames, and a pointer to re-scan from the Release
  Center. Honest by construction: gated to a real run (SIM/demo keeps its illustrative surfaces), an
  error leaves the panel empty rather than inventing changes, and untrackable files are reported as
  untrackable, never "unchanged". Suite green at 1642.

## Feature: Remediate review queue (AI Work Inbox) · #4598

The Remediate tab's AI Work Inbox stacks a rich EvidenceCard per finding; a 50-file scan opened as a
wall of expanded evidence a reviewer had to scroll past to find where to start. Continues #232 (search
+ per-card collapse, under v2 redesign) into a guided review queue — everything here is UI over
existing data and the existing decision path; nothing adds a second write path.

- **Severity + criterion facet filters for the inbox** (#248). A reviewer facing a dozen-plus items
  wants to chunk them — "just the critical ones", "just the 1.1.1s". `reviewInboxFilter.js` gains
  `itemSeverity` / `itemCriterion` (read off fields already on the item), `reviewFacets` (values
  actually present, each with a count — severities worst-first, criteria numeric) and
  `applyReviewFilters` composing search + severity + criterion while preserving the queue's priority
  order. The filter row renders only when there is more than one value to choose between.
- **Inbox opens collapsed — a scannable list, expand what you work** (#250). Cards default to
  collapsed so the inbox opens as headers (file · rule · severity). Mechanism matters: a seeding
  effect marks each card collapsed the first time its id appears and never again — it merges only ids
  *absent* from the collapse map, so a card the reviewer expanded survives the queue's background
  refetches instead of snapping shut under them; keyed off the id set, not queue identity.
- **Inline triage from the collapsed row, group-by-file, and a view that survives leaving the tab**
  (#251). The collapsed row now carries the AI's proposed fix (the literal `after` value or the shorter
  action hint) with inline ✓ Approve / ✗ Reject that go through the *same* `evAct` path as the expanded
  EvidenceCard — no second, divergent write path — with `preventDefault`/`stopPropagation` so a click
  acts on the item rather than toggling the `<details>`; hidden entirely in read-only replay. A "Group
  by file" toggle turns the flat list into per-document sections (one collapsible header carrying the
  file's worst severity and count, the same cards nested — `renderCard` extracted and reused verbatim
  so there is no second card markup to drift); `groupReviewByFile`/`worstSeverity` are pure and tested.
  Search, filters and the group toggle now persist in `sessionStorage` (`inboxPrefs.js`, keyed by run
  id so two scans don't share a filter); the per-card collapse map deliberately is not persisted. Both
  gaps surfaced dogfooding a 50-file scan.
- **Phase 1 clarity — one dominant review summary, inspect-only rows, scope disclosure** (#272; first
  slice of the Remediate redesign R4, `docs/remediate-redesign-spec.md`). The duplicated review
  counters collapse into one statement — "N findings need review across M documents" (both real counts;
  the hero no longer repeats it and its numeric pill is gone; no fabricated time estimate). Approve/Reject
  removed from the collapsed row: a decision needs the evidence, so the row is inspect-only and the
  controls stay in the expanded card. Progress label "reviewed" → "resolved". The scope-counting banner
  moves behind an "Assessment scope" disclosure so it no longer occupies the work surface.
- **Single-open accordion — default collapsed, guided sequence** (#273). The multi-open accordion
  auto-expanded the first card, burying the queue below the fold (an expanded card carries a document
  preview). Now: all collapsed by default with a single `openId`; clicking a row opens it and closes the
  previous (guarded so opening B is not clobbered by A's closing toggle); "Review N remaining issues"
  opens the highest-priority finding and scrolls to it (the old CTA fired a dead `acp:open-inbox` event
  nothing listened to); Save-and-continue auto-advances to the next finding; a lone finding auto-opens;
  the open finding persists per scan (`inboxPrefs.openId`) so returning to the tab reopens it. Bulk
  Collapse-all/Expand-all removed — "expand all" is the buried-queue state this exists to remove.
  Deliberately *not* in this PR: a per-finding time estimate on the row ("~5 sec") — queue items carry
  no est-time and this codebase does not fabricate numbers; surfacing it needs `etaMin` threaded through
  the queue builder, a separate data change.
- **Surfaced AI provenance on the review card from the real per-call zone, not the configured one**
  (#277; closes backlog W6). The GPU→CPU vision fallback is silent: a reviewer approving an alt-text
  draft never sees whether it came from the GPU model or the much weaker local CPU floor — they look
  identical. A provenance badge existed, but only inside the collapsed "Detection, provenance & audit"
  disclosure, and it read the *configured* provider zone from `/config` — exactly the value that lies
  when a fallback happens. A compact 🟢 Local / 🟡 Cloud chip now sits on the always-visible card,
  sourced from the actual `ai_calls` ledger: Remediate fetches `getScanAiCalls(scan_id)` once per scan
  (not per card) and builds a file→zone map — any cloud call on a file wins (privacy-conservative), a
  file with no AI call gets no badge (deterministic fix, nothing to claim); the actual zone wins over
  `aiProvenance().zone`, which appears only as a labelled "(configured)" fallback, and no badge is
  fabricated when neither is known. The buried provenance row and audit table read the same real zone,
  so surface and disclosure never contradict. This is the R12 finding made visible at the point of
  approval — verified live 2026-08-14. Suite green at 1645.
- **Replaced the expand-in-place card inbox with an Outlook-style master/detail remediation inbox,
  then retired the state it made dead** (#291, #299; backlog R4 Phase 2). Remediation is queue work —
  select, understand, act, next — and vertically-expanded cards make a reviewer scroll one finding while
  losing the rest of the workload. `remediationInboxModel.js` is the pure core: five remediation lanes
  (green review-auto / blue apply-suggested / amber manual / gray recheck / red blocked) with rail
  colours and actions, effort estimates, resolved-state, status tabs (All / Auto-fixed / Manual /
  Blocked / Resolved) whose counts partition the queue, priority/document/newest/fastest sorts,
  group-by-document, and `nextUnresolvedId()` for auto-advance. `RemediationInbox.jsx` is the two-pane
  view — a 38% work queue, a 62% workspace: selecting a row populates the detail pane (do / changed /
  act, in that order, with a sticky action bar and a before|after toggle) instead of expanding, acting
  auto-advances to the next unresolved finding, and manual findings get a guided state reusing
  `remediationGuide.fixSteps`. Wired into the live Remediate view with `onDecide` mapped onto the
  existing `act()` approve/reject/defer flow — first wire-in deliberately does not pass
  `onOpenWord`/`onRecheck` (their buttons are gated on the handlers). The old inbox's `renderCard`,
  `evAct`, facet/filter helpers and the `EvidenceCard`/`reviewInboxFilter` imports were removed with it;
  #299 then retired what #291 left constant — the single-open `openId` accordion (#273), the
  search/severity/criterion/group filter state (#248/#251) and their `inboxPrefs.js` sessionStorage
  rehydration, plus the orphaned module and test — no kept code references any removed symbol. Net: the
  #248/#250/#251/#273 card-inbox mechanics above are superseded by this component (search and facets
  now live inside it as render-tested behaviour). Frontend, not RULE_PATHS.
- **Folded auto-applied fixes into the inbox as green review-lane rows** (#300). Review-of-auto-fixes
  now shares the master/detail flow instead of a separate section. `autoFixRows(fixes, nameOf)` turns
  ACP's applied fixes / remediation diffs into green REVIEW-lane rows ("ACP fixed it — review the change"
  / Approve fix / ~5 sec) carrying before/after, with `af:…` ids that never collide with the human-queue
  ids; Remediate feeds a combined `[...human queue, ...autoFixItems]` and merges a local `ackd` map into
  the inbox decisions. An auto fix is already applied and re-scanned, so Approve *acknowledges* it
  (resolve + advance) and never re-applies; the human lanes still route to the HITL `act()` flow. The
  GroupedFixes summary stays for the at-a-glance count — slimming it is a follow-up.

## Feature: Estate coverage — three denominators and discovery at scale · #4597

A customer with a 30k-file estate could not see it: discovery listed the whole drive but the count the
UI showed was the *assessable subset*, so "unsupported" read as "passed" by omission. This makes ACP
count the whole estate honestly — discovered / assessment-eligible / remediation-eligible as three
denominators, never one percentage — and proves the discovery path holds at hospital scale. Spec: the
three-denominator model (#297, under Documentation).

- **Inventoried the whole estate, not just the scannable subset** (#290). New `api/estate_inventory.py`
  — a standalone capability-status classifier (assessable / metadata-only / unsupported / excluded) plus a
  whole-estate summary (discovered, assessment-eligible, by-format, by-status). `_search_drive` now unions
  *every* discovered file of any type and reports the summary via `scope_out['inventory']`, which already
  rides into the persisted scan report, so the funnel and composition views have real data. ACP-generated
  output is flagged EXCLUDED so it is not counted as the user's content. Assessment and remediation are
  unchanged — still only the scannable subset: this changes what is *counted*, never what is scanned.
  Follow-ups named: folder-scan parity (`_search_folder`), metadata enrichment via `DRIVE_FIELDS`
  (owners/size/sharing), and the frontend wiring (landed as #298/#301).
- **Made `run_scan` honour `FANOUT_MAX_FILES`, and made the inventory flag truncation** (#292). Two gaps a
  30k-file UTSW estate would hit: `run_scan` called `_list` with no `max_files`, so its whole-Drive path
  fell back to `_search_drive`'s 500-file / 2500-raw default — covering ~500 of a large estate while the
  "raise `ACP_FANOUT_MAX_FILES`" hint pointed at a knob that never reached it (production already used
  the fan-out path; this fixes the local/ADC path and makes the hint truthful). And
  `estate_inventory.summarize` now carries a `truncated` flag from the listing's `hit_cap`, so an estate
  larger than the ceiling is reported as a *floor*, never as a complete count — silent truncation is the
  one failure the inventory exists to stop.
- **A 30k-record synthetic Drive listing at UTSW hospital shape, for discovery/inventory scale testing**
  (#293). `scripts/scale_corpus.py` generates ~30k metadata records — heavy PDF/Word with a large
  image/video/loose-text tail — to exercise what only strains at scale: the inventory's composition and
  capability-status split, the funnel top, the department/visibility/age cuts. *Not* 30k real documents;
  assessment accuracy stays on the labeled corpus, and the docstring says so. The generator cross-checks
  its by-construction intent against `estate_inventory.summarize()` on all 30k, so a classifier that
  misbuckets a format at scale (a `.heic` as 'other', a native Google Doc missed) fails right there — the
  generator is itself a scale test of the classifier. A run yields ~62% assessable / ~38%
  metadata-only + unsupported — the honest blind spot the whole-estate view exists to surface.
- **Accuracy-at-scale: the labeled complex corpus embedded in the 30k estate** (#294). Detection is
  per-file and isolated, so it is scale-invariant; what scale can break is discovery + attribution — are
  the labeled files found among the estate, unique, assessable, labels intact, findings tied to the right
  file. `scripts/scale_accuracy.py` scatters `complex_corpus`'s labeled files (#287, known {SC: count})
  through the synthetic estate, proves discovery accounts for every one among the 30k, then scores each
  against its injected-SC floor by reusing the shipped `score_assessment.scan` path — the same measurement
  the docx scorecard makes, now on files inside a large estate. Metadata layer pinned engine-free (none
  dropped/deduped; embedding raises the assessable count by exactly the labeled files; deterministic);
  per-file engine scoring runs via CLI/CI where the analyser exists.
- **Pinned the scale invariants end-to-end: truncation fires past the cap, shared-drive dedup, and
  per-operator isolation** (#295, #296). #295 drives the real paging path (`_search_drive` →
  `_list_drive_page_all`) with a mocked Drive that pages past the raw cap (3000 files > the 2500 floor)
  and asserts both `scope['truncated']` and `scope['inventory']['truncated']` fire — and that a small
  estate is *not* falsely flagged. #296 (~50 identities; toward backlog R11/R13): a file surfaced 50×
  (multi-parent / Shared Drive / paging overlap) collapses to one document — 2000 sightings of 40 files →
  40 discovered, not 2000; and because ACP scans as the signed-in operator (delegated token), two
  operators' estates stay disjoint — A's scan never surfaces B's files. Both engine-free.
- **An estate coverage view rendered from the scan's real inventory, on the Overview dashboard** (#298,
  #301). `estateFunnel.js` (pure, node-verified) models the nine-stage funnel, composition rows
  largest-first with an assessable/blind-spot flag, the status breakdown, assessable %, and truncation;
  `EstateCoverage.jsx` renders the funnel + format composition + capability-status split. Truncated
  estates render as a *floor* (≥ N, TRUNCATED badge), never as complete; unsupported is its own status,
  never folded into passed. #301 gives it a home: the Overview renders it from `run.scope.inventory`,
  guarded to appear only once discovery has inventoried the estate. Funnel stages 1–3 (discovered /
  inventoried / assessment-eligible) are real from the inventory; stages 4–6/7 (assessed, issues,
  remediation-eligible, remediated) derive from the file rows; human-review and published stay
  'pending' rather than showing a guessed number until that workflow state is threaded through.

---
- Drill a capability-status count down to the files behind it: `summarize()` emits a
  capped per-status sample into `scope.inventory.samples` and EstateCoverage renders a
  click-to-expand list under each chip. `by_status` stays the TRUE total so the drill-down
  reads "Showing N of <total>" — an unsupported bucket of thousands is never mistaken for
  the handful sampled; a paginated per-file export is a separate follow-up (#303).
- Owner / size / sharing on the drill-down, sortable for triage: `size`, `owners`, `shared`
  added to `DRIVE_FIELDS` (same list page, no extra call); externally shared files get a
  SHARED badge; sorts biggest-first, shared-first, or by name — the three lenses that matter
  at 30k-file PHI-estate scale. Missing metadata degrades to null/false, never a wrong value (#304).

---

## Feature: Discover & Assess lifecycle rules

Two conflated scopes pulled apart, per the "Discover & Assess Lifecycle Rules" PRD (Deva). Discover must
inventory *every* file so nothing is invisible by omission; Assess is narrowed on purpose to supported
document types and a chosen set of WCAG criteria; and configurable rules — folder/path, modified-before —
govern archive / delete / tag as *candidates* during the same discovery run, with flagged files kept out of
Assess by default. Built as eight independently-CI'd PRs across isolated worktrees on disjoint files,
foundation first so the shared `store.py` schema never became a merge chokepoint.

- **Lifecycle inventory foundation** (#310). The per-file `scan_inventory` row gained the source metadata
  lifecycle rules need — `created_at`, `source_modified`, `owner`, `parent_folder`, and a per-file
  `discovered_at` (the scan's `started_at` was the only timestamp before, and it is not per-row) — plus a
  7-state `lifecycle_status` (Active / Archive Candidate / Archived / Delete Candidate / Deleted / Failed /
  Exempted) carrying the rule id and reason that set it, and a `file_tags` table for system/user tags.
  `documents.source_modified` and Drive `createdTime`/`parents` were added so the modified-before and
  folder conditions have real inputs. Additive only — no primary-key change, no behaviour change; landed
  before any consumer so three feature tracks could build in parallel without colliding on `store.py`.
- **Rule conditions: folder/path and modified-before** (#309). The disposition engine gained `path` /
  `parent_folder` fields with a case-insensitive `prefix` op (target everything under `/Finance/`) and
  `modified_at` / `created_at` date fields with `before` / `after` ops reading `documents.source_modified`
  — malformed or missing dates evaluate false, never raise. Exactly the two condition kinds the PRD names;
  39 unit tests.
- **Tag as a disposition action** (#314). Added the PRD's third action alongside archive and delete: `tag`
  attaches tags via the new `file_tags` table and — unlike archive/delete — needs no Drive connection, so
  it works for any source; a tag policy with no tags is rejected at creation. Frontend gained the Tag
  action + a tags input.
- **Discover inventories every file type, with full metadata** (#315). Discovery previously persisted
  per-file rows only for the scannable subset (docx/pdf/pptx/xlsx/html); everything else lived as counts
  plus a capped sample. Now every accessible file — media, archives, executables, extensionless — gets a
  durable inventory row with its real MIME, owner, size, created/modified date and folder lineage, on both
  the Drive and SharePoint paths. The safety property is explicit and tested: Assess re-derives
  assessability from name + real MIME and never downloads a non-assessable file, and the real source MIME
  is kept separate from the overloaded export-selector MIME so a plain `application/pdf` is never fed to
  the Google-export map. This changes what is *inventoried*, never what is scanned.
- **Rules evaluated during Discover; flagged files excluded from Assess** (#320). After discovery persists
  the inventory, enabled policies run over each row candidate-first: an archive match sets Archive
  Candidate, a delete match Delete Candidate, a tag match writes tags — each recording the matching rule id
  and a human reason, no Drive action taken. Idempotent (a re-run adds no duplicate tags or audit rows),
  Exempted files are never moved, and delete overrides archive only with an explicit `override_archive`
  flag and an authorized actor. Assess then excludes Archive/Delete-flagged files by default, with an
  owner-gated `include_lifecycle_flagged` override, and the assess record retains the status + exclusion
  reason that applied at run creation.
- **Assess scoped to a chosen WCAG code-set, with a live eligibility count** (#311, #316). A read-only
  `/assess/eligibility` endpoint and a Core-17 code-set catalog (`{code, name, formats}`) back a new
  Assess-time scope UI: document-type selection moved out of Discover into Assess, a Core-17 picker showing
  code + name ("1.4.3 — Contrast (Minimum)") for one / several / all criteria, and a debounced "N files
  eligible" count before the run. Core 17 is the canonical set — the "15" a draft mentioned is only its
  docx-format projection. The old "two filters, last-touched-wins" ambiguity (ScanSetup vs FileTypeConfig
  both writing `scan_scope`) was resolved by making the Assess selection the single authority; Discover
  lost its file-type gate and gained a source/folder/path Document Location view filter.
- **Corrected a RESET-safety regression I introduced** (#312). The foundation's `file_tags` table was not
  declared in `_ANALYTICS_TABLES`, so the reset-completeness guard (`test_reset_leaves_no_customer_data`)
  failed closed on `main` — file_tags is per-file customer output and must be purged on RESET. One-line
  fix. Honest cause: I let `--auto` merge the foundation before its full backend suite finished, and a
  targeted test run had missed that guard; every merge after this waited on the required checks actually
  going green, and I switched the merge watch to the required Actions jobs so a stuck Netlify preview could
  not hang it. (A second session fixed the same bug in parallel as #313, leaving a duplicate list entry —
  harmless; cleanup flagged.)

## Open items (backlog candidates)

- **The docx header/footer parity audit is complete.** All six body-only content checks now read
  the header/footer/note parts: 2.4.4 (#214), 2.1.2/3.3.2/4.1.2 (#229), 1.4.11 (#230), 3.1.2 (#226)
  and 1.4.1 (#227). The never-fail-a-scan contract that backs the registry detectors is pinned
  registry-wide (#224, #228). No open siblings remain from this sweep.

- **The v2 redesign is a fork** — `frontend-v2` was forked so it could move without risking
  the live SPA, and both are now being maintained. It needs a merge path before they diverge
  further.
- **Unfinished work parked on a branch (#130)** — a retiring worktree's uncommitted changes
  were committed explicitly unreviewed and unfinished, based on `5d81724`, several commits
  behind main at the time. It was pushed so the work is recoverable and visible to the
  collision checks other sessions run, not because it is done. Someone needs to decide whether
  to finish it or drop it.
- **`#UTSW` is used as a customer tag in commit subjects**, not a PR number. If UT Southwestern
  work is tracked in ADO, that is a candidate linkage.
- **Uncommitted worktree state** — `.claude/worktrees/`, `ACP_DOCX_WCAG_Fixtures/` and its zip
  are untracked in the working tree. *(2026-08-18: still untracked — `ACP_DOCX_WCAG_Fixtures.zip`,
  `ACP_DOCX_WCAG_Fixtures/`, plus two new ones, `Radnet-logo.png` and `docs/Archive.zip`;
  `.claude/worktrees/` no longer shows in `git status`. Decide whether the fixtures belong in
  `test-corpus/`, and whether the logo and archive belong in the repo at all.)*
- **Two corpus generators disagree about field names** (#188) — both readers now tolerate either,
  but which generator is authoritative is an open decision, not a resolved one.
- **RESOLVED — the two redundant Azure Pipelines are disabled.** `acp-ci-github` and
  `jeremyyuAWS.acp` were set `queueStatus: disabled` in Azure DevOps (see the Continuous-deployment
  Feature), completing #235's retirement; they no longer post checks on GitHub PRs. `acp-ci` (the
  TfsGit pipeline on a different repo) was deliberately kept enabled. Left recorded rather than
  deleted so the decision — and that `acp-ci` was spared on purpose — is legible.
- **The scheduled production probe was failing on `main`** (`.github/workflows/monitor.yml` →
  `scripts/monitor.py` against `ACP_FQDN`) — `completed/failure` repeatedly, e.g. on `de556b5`. Two
  monitor/deploy causes have since been fixed: a false deploy-drift red from a CI-only file (#237)
  and a real one where an approved-late deploy shipped a stale sha (#238). A dedicated investigation
  of any remaining cause (prod health vs. a broken probe / misconfigured `ACP_FQDN` / `ACP_MONITOR_KEY`)
  is running in a separate session; confirm the probe is green before closing this.
- **This log was lost once already.** It was committed locally on 2026-08-08 and discarded by a
  `git reset --hard origin/main` in a parallel session, because it had never been pushed. It was
  recovered from the dangling object. Push it, or it will happen again.
- **Backlog Phase R — 13 pilot-readiness gaps** (#270, 2026-08-14), ahead of the 3-user pilot.
  Ops-blocking (R1–R3): the wedged 3a/readiness GitHub Actions deploy — merged green but not live
  (this is the same class of drift the production-probe item above tracks; confirm the probe and the
  live sha together); the unwired RunPod serverless vision lane; rotating the exposed RunPod key.
  Features (R4–R9): the Remediate drawer redesign (Phase 1 shipped as #272/#273; the queue + right
  drawer, the AI-Work-Inbox → Review-queue rename across surfaces, and a grounded per-finding time
  estimate remain), Monitor tab → real `/source-status` wiring, the Phase 3b scope chip (the run
  payload already projects `scan_scope` for it, #267), Phase 3c per-user config, WCAG capability
  completion for the 12 not-ready cells (#268 greys them out; split 4 quick-fixes / 4 builds / 4 N/A
  + 3 appliers), optional Archive auto-fire. Testing (R10–R13): the CI fixture-verification harness for
  the understated cells (capability counts are source-verified, not fixture-run), a multi-user
  concurrency load test, RunPod E2E verification, an isolation-off invariant test.
  *(Status after #276–#301, 2026-08-18 second pass:* **R2** downgraded to in-progress — env is set on
  `acp-app` but the runtime still selects local; most likely the `runpod-api-key` secret not resolving,
  ties to R3 (#276); #286 gives the lane a 240s cold-start timeout and records the failed cloud attempt
  in `ai_calls` so the remaining cause is diagnosable from the UI after deploy. **R12** moved from
  unverified to *verified failing* in prod on 2026.8.14.1 (#276), with the objective re-test recorded;
  #277 makes the miss visible on the review card. **R4** advanced: the master/detail inbox is built and
  wired (#291), dead accordion state retired (#299), auto-fixes folded in as green rows (#300); the
  AI-Work-Inbox → Review-queue rename and a grounded per-finding time estimate remain (#300's "~5 sec"
  is the auto-fix lane's fixed effort, not a measured estimate). **R5** closed — Monitor tab reads the
  real `/source-status` (#278). **R8** closed for four of the 12 cells — xlsx 1.4.1/1.4.11/4.1.2 and pdf
  2.4.3 declared (#289); eight remain. **R10** partly met — a named declare-gate proves those four
  detectors emit (#288); the general fixture-verification harness for understated cells is still open.
  **R11/R13** partly met — a ~50-identity dedup + per-operator isolation test lands engine-free (#296);
  a real multi-user *load* test and the isolation-*off* invariant remain. R1 (wedged deploy), R3 (key
  rotation), R6 (3b scope chip), R7 (3c per-user config), R9 (Archive auto-fire) unchanged.)*
- **Backlog Phase W — nine workflow-completeness gaps** (#274, 2026-08-14), observed from drawing the
  connected-source→governed-content flow and *not yet confirmed in source*. W1–W3 are dead ends a
  released file cannot route around: no publish target for the fixed copy, rejected fixes dead-end,
  re-validate may not re-score the whole file. W4–W9 are scale/honesty polish. Each names the file to
  confirm in first — confirm before estimating. *(2026-08-18 second pass:* **W6** closed — AI provenance
  on the review card now reads the real per-call zone (#277), and #286 applies the same honesty to the
  provenance ledger itself. The pilot one-pager (#281) traces "one library / staggered scans" to R5/W9.
  W1–W5, W7–W9 otherwise unchanged and still unconfirmed in source.)*
- **New from the 2026-08-14 docs sweep, not yet in the backlog phases** — the pilot-SOW SharePoint gaps
  (#285: multi-site orchestration is the biggest; a folder match field in the disposition engine is a
  small build; native-column write is out of scope by design), the discovery & triage build order (#283:
  `_ARCHIVED` recognition of the customer's 17,512 already-archived files, content-hash dedup,
  version-supersession, sharing/access signals — all unbuilt), the estate-inventory follow-ups named in
  #290 (folder-scan parity in `_search_folder`, `DRIVE_FIELDS` metadata enrichment), the funnel's
  human-review/published stages still 'pending' (#301), and the multimedia-captioning LOE (#280: ~10–14
  pw Phase 1, +8–16 pw Phase 2, GPU-dependent). Candidates for ADO Tasks once scoped.
- **Two roadmap corrections this sweep worth carrying into ADO rather than re-estimating**: the live
  Drive write-back "bug" was verified stale and its ~2–3.5 person-day estimate corrected to ≈ zero
  (#258); and the `deva-final` → `engagement-14` preset rename means any environment still persisting
  `scan_scope=deva-final` must be re-set by hand (#259).
- **Lifecycle scoping by location/owner/department is deferred (PRD C4 / AC-09)** — Assess code-sets
  scoped per folder/owner/department with a precedence resolver was explicitly held out of the first pass
  as the heaviest, net-new axis (`scan_scope` today has only criterion × format). The natural fast-follow;
  the eligibility endpoint and Core-17 picker it would build on already exist (#311, #316).
- **Lifecycle PRD — thin-UI / semantics follow-ups, backend complete.** (a) The new folder/path and
  modified-before *conditions* evaluate end-to-end (#309/#320), but confirm the disposition rule-builder in
  `Disposition.jsx` actually exposes those fields to click together — may be a small UI wire-up. (b) The
  delete-over-archive "authorized actor" (PRD §6) is interim: an `override_archive` flag + a non-`demo`
  actor, because the codebase has no RBAC role model — worth a product decision. (c) Tags are keyed two
  ways — discover-time by `scan_id`/`file`, approval-time disposition by `doc_id`/`path` — reconcile if a
  single tag view must span both. (d) State reconciliation (discovered → active/archived/flagged/…,
  AC-14): `store.count_lifecycle_by_status` exists but no dashboard renders it yet. (e) The duplicate
  `file_tags` entry in `_ANALYTICS_TABLES` (from #312 + #313 fixing the same bug) is being de-duplicated in
  a separate session.

---

## Sync log

- **2026-08-08** — Log created, covering 2026-08-01 onward (38 commits). Seven Features
  written: SharePoint source, operator scan scope, v2 redesign, remediation write-back,
  assessment correctness, multi-tenancy/control plane, and local model benchmarking.
- **2026-08-08 (later)** — Recovered this file after a parallel session's
  `git reset --hard origin/main` discarded the unpushed commit that introduced it, then added
  12 commits (#185–#196). Three new Features: Dependency security, Alt-text generation and
  grounding, and Test corpus and CI. Six Tasks appended to the v2 redesign.
- **2026-08-10** — Documented #198–#231 as landed on `origin/main` (head `2f1f692`). Five new
  Features: docx Core-17 criterion coverage, docx running header/footer parity, Capability registry
  (ADR 0031), PHI privacy and document access control, and Continuous deployment to Azure. Tasks
  appended to SharePoint source, v2 redesign, Alt-text grounding, Assessment correctness, Test
  corpus and CI, and Documentation. The delivery-log commits (#197, and the #196 extension) and the
  never-fail-a-scan test PRs are excluded as non-feature work. Open item added for the two
  still-open header/footer siblings (#226, #227). The header/footer parity Feature is work I did
  this session (#229 merged, #230 authored+merged).
- **2026-08-10 (reconcile)** — `origin/main` advanced to `3eb4883` while the above was being
  written; #224–#228 landed. Folded them in: 3.1.2 (#226) and 1.4.1 (#227) appended to docx
  header/footer parity — the audit is now complete across all six body-only checks; the
  never-fail-a-scan contract (#224, #228) added to Capability registry; Chain-B docs (#225) to
  Documentation. The "two siblings still open" Open item is replaced with an "audit complete" note.
  Sync marker advanced from `2f1f692` to `3eb4883`.
- **2026-08-10 (later)** — Added #232 (AI Work Inbox collapsible + searchable) as a Task under the
  v2 redesign; it merged as `39157ea`. #233 — the delivery log's own reconcile commit (`6484160`) —
  is excluded as non-feature work, as the earlier log commits are. Sync marker advanced from
  `3eb4883` to `6484160`.
- **2026-08-10 (later still)** — Added #235 (retire the redundant Azure Pipelines CI's auto-triggers)
  as a Task under Test corpus and CI; it merged as `d9b5f14`. Two Open items recorded from tracing
  it: the ADO-side pipeline disable/delete a commit cannot reach, and a separately-discovered
  failing production probe (`monitor.yml`). #234 (log commit `de556b5`) is excluded as non-feature
  work. Sync marker advanced from `6484160` to `d9b5f14`.
- **2026-08-10 (evening)** — Added #237/#238 to Continuous deployment to Azure (monitor false-drift
  fix; deploy resolves `main` at approval time) and #239 to SharePoint (runtime Entra config +
  Microsoft sign-in button). Recorded the ADO-side completion of #235 — `acp-ci-github` and
  `jeremyyuAWS.acp` disabled in Azure DevOps (ops, no commit), `acp-ci` left enabled — as a Task and
  resolved its Open item. #236 (log commit `9ad4c4f`) excluded as non-feature. A local shell-PATH fix
  (`~/.bash_profile`/`~/.bashrc` for `gh`/`az` in VS Code) is dev-environment tooling, not project
  work, so it is not logged. Sync marker advanced from `d9b5f14` to `1b49608`.
- **2026-08-18** — Standup sweep, mode `clean`. 35 commits added (#241–#275, 2026-08-10 → 2026-08-14)
  as 30 Tasks. Two new Features: **Release Center** (2 Tasks — #249/#252 rename + honest policy panel
  and confirm-before-release; #253/#254 source-staleness baseline, `/source-status` endpoint and the
  Release Center warning) and **Remediate review queue (AI Work Inbox)** (5 Tasks — #248, #250, #251,
  #272, #273; continues #232 from the v2 redesign). Tasks appended to existing Features: Operator scan
  scope +6 (#259, #260, #261/#262, #266, #267, #268), v2 frontend redesign +5 (#263, #264, #265, #271,
  #275), SharePoint as a document source +3 (#241/#242/#243, #245, #247), Documentation +4 (#256,
  #269, #270, #274), and one each to Alt-text generation and grounding (#255), Test corpus and CI
  (#257), Remediation reaching the file (#258 — recorded as a correction: the Drive write-back bug was
  verified stale), Assessment correctness (#246) and Continuous deployment to Azure (#244). Open items:
  the Phase R (13 pilot-readiness) and Phase W (nine workflow-completeness, unconfirmed in source) gap
  lists summarised; the two roadmap corrections (#258, #259) noted; the existing "Uncommitted worktree
  state" item updated in place rather than duplicated — `ACP_DOCX_WCAG_Fixtures.zip`,
  `ACP_DOCX_WCAG_Fixtures/`, `Radnet-logo.png` and `docs/Archive.zip` remain untracked and uncommitted
  in the working tree. The two log-maintenance commits in the range (`c0be3ccb` #240 log #237–#239;
  `055b01ac` bind ADO work items) are skipped as non-feature, as earlier log commits were. No `· #id`
  bindings were changed and none were invented for the new Features. Sync marker to be advanced from
  `1b49608` to `055b01ac`.
- **2026-08-18 (second pass)** — After the first pass was committed as `47c3bda4`, a fetch surfaced 26
  more commits already on `origin/main` (#276–#301; dated 2026-08-14 → 2026-08-17, not all 08-14).
  Added as 21 Tasks. One new Feature: **Estate coverage — three denominators and discovery at scale**
  (6 Tasks — #290 whole-estate inventory, #292 `FANOUT_MAX_FILES` + truncation flag, #293 30k synthetic
  listing, #294 accuracy-at-scale, #295/#296 scale invariants, #298/#301 EstateCoverage view; spec #297
  filed under Documentation). Tasks appended to existing Features: Documentation +6 (#276 R12/R2
  correction, #280/#282 engine architecture refs + captioning LOE, #281 pilot one-pager, #283 discovery
  & triage spec, #285 SharePoint-vs-SOW gaps, #297 three-denominator model), Remediate review queue +3
  (#277 provenance chip, #291/#299 master/detail inbox — recorded as superseding the #248–#273 card-inbox
  mechanics, #300 auto-fix rows), Test corpus and CI +2 (#284 robustness corpus, #287 complex corpus),
  and one each to Operator scan scope (#279 derived level), Alt-text generation and grounding (#286
  RunPod timeout + surfaced miss), Capability registry (#288/#289 four cells declared behind the R10
  gate) and Release Center (#278 Monitor source-drift panel). Open items edited in place: Phase R
  status per item (R2 downgraded, R12 verified failing, R4 advanced, R5 closed, R8 four-of-twelve, R10
  and R11/R13 partial), Phase W (W6 closed), plus a new item collecting the gaps the 2026-08-14 docs
  sweep named that are not yet in a backlog phase. Untracked files unchanged from the first pass. No
  `· #id` bindings changed or invented. Sync marker to be advanced from `055b01ac` to `47c3bda4`.
- **2026-08-18** — Created ADO Features under Epic #3664 for the three unbound Features from
  the sweep: **#4597** Estate coverage, **#4598** Remediate review queue, **#4599** Release
  Center (Feature type, Iteration 10, MovaIO-Build, Active). IDs bound to the headings above.
- **2026-08-18** — Three commits (#302–#304, 2026-08-18) landed while the previous mark was
  being pushed and were briefly covered-but-unlogged; recorded now: two under Estate
  coverage (#303 status drill-down with honest cap, #304 owner/size/sharing triage lenses),
  one under Continuous deployment to Azure (#302 ollama models baked to `/models` — the root
  cause of the production vision lane never running).
- **2026-08-18** — Created ADO Features under Epic #3664 for the fifteen remaining unbound
  Feature headings (#4600–#4614: SharePoint, Operator scan scope, v2 redesign, Dependency
  security, Alt-text, Test corpus & CI, Remediation reaching the file, Assessment
  correctness, Multi-tenancy, Local model benchmarking, docx Core-17, docx header/footer,
  Capability registry, PHI privacy, Continuous deployment). Feature type, Iteration 10,
  MovaIO-Build, Active; each description carries the heading's first 12 Tasks. IDs bound
  above. `## Documentation` deliberately left unbound — it is cross-cutting, not a capability.
  Every Feature heading in this log is now bound.
- **2026-08-18 (evening)** — Documented the "Discover & Assess Lifecycle Rules" PRD as one new Feature
  (**Discover & Assess lifecycle rules**, unbound — a new capability that doesn't fit the estate-coverage
  Feature), covering eight PRs: foundation schema (#310), folder/path + modified-before conditions (#309),
  Tag action (#314), inventory-all-types (#315), rule-eval-during-Discover + Assess-exclusion (#320),
  Core-17 code-set + eligibility endpoint (#311), the Assess/Discover frontend (#316), and the RESET
  classification fix (#312). Recorded the honest #310→#312 correction (premature `--auto` merge before the
  full suite; caught by the reset guard, fixed forward). Added #321 (backend-suite sharding) under Test
  corpus and CI. Two Open items added: the deferred C4 location/owner/department scoping (AC-09) and the
  lifecycle thin-UI/semantics follow-ups. Excluded as non-feature: the parallel duplicate reset-fix (#313,
  same bug as #312). Sync marker advanced from `d7c7a055` to `27827405`.
