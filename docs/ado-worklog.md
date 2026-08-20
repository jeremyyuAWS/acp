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
- **End-to-end validated SharePoint discovery on the deployed app** (2026-08-18, no PR — testing, not
  code). Drove the deployed app (v2026.8.18.2) as `jeremy_acp@fgxlxj` via Microsoft SSO against a
  synthetic ~158-document medical estate uploaded to the fgxlxj Communication site, Core-17 · all four
  formats. Confirmed discovery → download → per-file WCAG assessment all work against real SharePoint
  content. Surfaced that `_sp_list` enumerates each library via Graph `driveItem search(q='')` — an
  index-backed, eventually-consistent call — so a scan run minutes after a bulk upload under-reports the
  estate: the first scan discovered **39 of ~158** files, and the same index was measured climbing
  39 → 157 → 158 as it caught up (library `ItemCount` = 374 proved the upload was complete; 39 ≪ the
  200-file cap ruled that out). Filed as GH #333, with the recovery confirmed and commented there.
- **Carried the drive identity to the download, so SharePoint files are fetched at all** (#481). The files
  were never "unreadable" — they were never **fetched**. `handlers`' `norm` dropped `driveId` from the
  scanner record, so the inventory row stored no drive identity, so nothing downstream marked the item as
  SharePoint, so `_download` fell through to the Google Drive branch and handed a Graph item id to
  `files().get_media()` — which raised, was caught, and recorded `status='error'` (the catch-all the UI
  renders as "file unreadable") for **every** SharePoint/OneDrive file in a fan-out scan. A regression, not a
  gap (`_sp_list` carries `driveId` per file for exactly this). The fix threads `driveId` through `norm` so
  the download routes to Graph. Paired with #483, which stopped the drawer mislabelling the symptom.

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
- **Carried the per-document selection through to the certification facts** (PRD 6.1, #410). Criteria and
  formats funnel through the single `scan_scope` gate, so Assess/Remediate/Publish inherit them for free
  — but the operator's per-document selection (marking a **subset** of documents in-scope in Remediate,
  `triage='inscope'`) lived only in `scan_decisions`, invisible to the verdict facts: the Remediate and
  Publish actions already honoured it (explicit file list), but the Assess status card and the
  conformance report counted the whole estate regardless. Added a per-document twin applied at **read
  time** (the marks are made after traces are written, so a scan-time freeze cannot work):
  `assessment_policy.selected_documents(decisions)` (once any file is in-scope, only in-scope files
  stay), and an opt-in `get_certification_facts(..., apply_document_selection=…)` that only the two
  aggregate readers (scan_status, report.pdf facts) opt into — `file_status`, the coverage matrix and
  every other caller see the whole estate, so per-file cards are unaffected. Gated so an unscoped run, or
  opting in with no marks, is byte-for-byte identity. `Matrix-Note: none`.
- **Per-user scan-scope override, end to end (ADR 0035)** — #424/#429/#445. #424 wired the stage-1
  override into `active_scope` as a **widen-only union** (owner default ∪ per-user override, per format),
  threaded through the two scan-listing chokepoints (`scanner._scope_for_listing` /
  `handlers._scan_discover`) and frozen once into `scan_runs.scope`: a user may assess **more** than the
  owner mandated, never less. #429 added the non-admin `GET/PUT/DELETE /settings/mine` route, keyed to the
  signed-in email so no one can write another user's scope (malformed scope → 422 and NOT stored, matching
  the admin PUT; "" / {} store as "no restriction"). #445 shipped the Settings-UI surface: `ScopeGrid.jsx`
  extracted from `ScanScope.jsx` as a shared presentational grid with a `lockedHas(sc,f)` prop (the
  refactor is behaviour-preserving — the existing 51 ScanScope/assess tests stay green), and `MyScanScope.jsx`
  renders the owner-mandated pairs **locked-on** (making widen-only visible), lets the user add pairs, and
  saves via PUT (additions only) or DELETE (fall back to org default).
- **Choose the folders each source scans — and actually apply it** — #441/#451. #441 put a "Scans:" row on
  each connected-source card showing "Entire Drive" or the chosen folders as named chips with Edit; the
  selection is a property of the **connection** (`GET/PUT /sources/locations`), not of one scan, so "New
  scan" needs no picker. Previously the only folder picker lived on Discover, reachable *after* a scan had
  already read the whole estate. #451 added child-folder **exclusions** (an unchecked child under a selected
  parent becomes an explicit exclusion, pruned at the **walk** not post-filtered) and fixed two bugs that
  made the whole feature cosmetic — the saved folder scope was not being applied at scan time.

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
- **Scoped Platform settings to access management — Owners + Users only** (#319). Removed the other
  six tabs (Scoring rules, Estate, File types, Remediated storage, Disposition, Data reset + its
  AI-provider governance panel); default tab is now Users. **Hide, not delete:** the three panels local
  to `Settings.jsx` (`ResetData`, `DriveMirror`, `AIProvidersPanel`) are exported and kept, the four
  imported ones live in their own untouched files, and the SIM-write-honesty guard — whose header
  documents it catching two real production incidents — now drives `DriveMirror` directly instead of
  through the removed "Remediated storage" tab, so no admin feature or safety test was lost. The Users
  tab gained equal-weight onboarding for both sources: **Microsoft** (the #308 Entra guest invite when
  configured, else a guided manual-Entra link that holds no Graph permission and ships dark, preserving
  ADR 0033) and **Google** (whitelists a Gmail in one step, mirroring the invite's auto-add, and surfaces
  the OAuth test-user step — the tester then signs in with Google and their Drive is a read-only source).
  New `settingsAccessScope.test.jsx` pins the two-tab scope, the kept-code exports and both onboarding
  cards incl. a functional Google whitelist; `simAdminWriteHonesty`/`inviteTester` updated to the new
  structure. Full v2 suite green at 1687; `vite build` clean.

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
- **Balanced the four shards by measured time, not test count** (#322). Added `.test_durations` so the
  suite splits across the four runners by wall-clock, not an even count — a few slow modules no longer
  pin one shard. Another session's follow-up to #321, recorded here as it landed in this window.

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
- **Ask which account at sign-in, for Google and Microsoft** (#453). A browser with one signed-in Google
  session went straight through on that account — GIS was called as `requestAccessToken()` with no prompt,
  MSAL as `loginPopup({ scopes })` — both silently reusing the single existing session. That is right for a
  token refresh and wrong for a **sign-in**, the one moment the user chooses who to be; it also made the
  ordinary setup impossible without a second Chrome profile (a personal Google Drive alongside a work
  Microsoft account). The two data connections were always independent (Drive rides `X-Drive-Token`,
  OneDrive/SharePoint rides `X-SP-Token`), so only the missing chooser was in the way — now added for both.

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
- **Brought the architecture docs current for the engineering deck** (#432, #438, #439, #444). The
  slide deck `docs/acp-architecture-deck.md` had gone materially stale (last verified 2026-07-29):
  refreshed the AI lane (five vision adapters, not Ollama+RunPod; text default `llama3.2`; the
  local-floor → acceptance-gated → GPU/cloud escalation; the in-tenant Azure T4 via `gpu_up.sh`
  alongside RunPod serverless), added a dedicated **Observability** slide (Langfuse **v2 on one Postgres
  today, v3+ClickHouse the committed migration**; the two-trace Scan/Assess model + `compliance_score`;
  the HMAC-filename / counts-and-lengths PHI invariant), a **Sources** slide (Drive / SharePoint / SMB),
  replaced the obsolete "manual deploy" headline weakness with the **two-chain CD** (prod approval-gated
  + unattended staging), and added the accessibility status model (ADR 0026 — `not_applicable` leaves the
  coverage denominator). #438 firmed the Langfuse v3 wording from "optional upgrade path" to a committed
  migration. (The actual v3/ClickHouse cutover has SINCE shipped — #449/#447, logged under Observability
  above — so the deck's Observability slide now needs a follow-up to say v3 is *live*, not planned.)
  #439 patched the long-form `acp-architecture.md` to match (Movate AccessOps naming, the
  five-adapter AI lane, per-user scope ADR 0035, the SMB connector's auth posture, the staging tier).
  #444 added two **Scan → Assess → Remediate + vision/GPU routing** slides: an ASCII workflow showing that
  only the image SCs (1.1.1, 1.4.5/1.4.9, scanned-PDF) enter the vision lane while deterministic SCs stay
  CPU, plus region/GPU-tier tables with real sizes (`NC8AS_T4` = 8 vCPU + 1× **T4 16 GB** running
  `qwen2.5vl:7b`; RunPod serverless; the in-process CPU floor). Honest caveats stated on-slide: no Asia
  region is live today (single env + Langfuse eastus2); the RunPod GPU class is configurable.
- **Updated the deck's Observability slide to say Langfuse v3 is *live*** (#457) — the follow-up the
  architecture-deck entry above flagged. #438 had framed v3/ClickHouse as the *committed migration*; the
  cutover then shipped (#449/#447), so the slide was stale on merge. Corrected to what is deployed: v3 is
  live on a dedicated Azure VM (`acp-langfuse-v3`, `Standard_D4s_v3` + 128 GB Premium disk, eastus2,
  ClickHouse + Redis + MinIO + Postgres via docker-compose behind Caddy/TLS); the trigger (a 44-document
  scan hung the v2 Session view); why a VM rather than Container Apps (ClickHouse needs real local disk,
  which ACA's Azure Files/SMB mounts fight); and the host-only cutover (LANGFUSE_HOST repoint + keys
  re-seeded, no app change, v2 deleted). The weaknesses slide's "v2 is the ceiling" line was replaced by
  the real new tradeoff — v3 is a self-managed VM to patch/back-up/TLS, provisioned by a runbook not the
  pipeline — and both topology ASCIIs + the Azure inventory now read `acp-langfuse-v3` (VM), not the v2
  Container App. Docs-only, not RULE_PATHS.
- **ADR 0037 — staged, bounded assessment pipeline (measure-first)** (#464, Track B design). The design for
  parallelising the assessment fan-out at pilot scale without the failure modes uncontrolled concurrency
  would cause — the load-bearing principle being to tune worker counts from **measured** per-stage time, not
  guesses. Grounded in what already exists (a bounded worker pool, per-file isolation, idempotent upserts,
  retry + dead-letter #347, checkpointed progress, safe cancellation, Langfuse tracing), it corrects the
  real gaps: a flat pool where five stages with opposite constraints share one concurrency limit, no GPU
  micro-batching / VRAM-shaped limit, and no per-stage instrumentation to even locate the bottleneck.
  Decides: separate the chain into bounded per-stage pools over the existing durable jobs queue; per-stage
  concurrency as benchmark starting points (not constants); GPU gets only vision work, micro-batched, with
  concurrency the knob most likely LOWERED by measurement; adaptive counts driven by
  throttling/CPU/VRAM/DB-latency/error signals; plus the full safety contract. Design only — no runtime
  change yet. Docs-only, not RULE_PATHS.
- **Reconciled the long-form `acp-architecture.md` to current** (#475). Patched for what shipped since #439:
  §8 Observability rewritten to Langfuse **v3 live** (ClickHouse + Redis + MinIO + Postgres on the
  `acp-langfuse-v3` Azure VM, why-a-VM-not-Container-Apps, host-only cutover); §9 corrected per-user scan
  scope from "in progress" to **wired end to end** (widen-only union through the two listing chokepoints,
  frozen into `scan_runs.scope`, `/settings/mine` + editor), plus the sign-in account chooser and
  folder-level source scope; §1 diagram + deps gained the in-tenant Azure T4 and the v3 VM; §11 added the
  flat-worker-pool concurrency weakness with **ADR 0037** named as the committed-but-unbuilt fix. §2–§7 core
  reviewed and already current. Docs-only, not RULE_PATHS.

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
- **Deployment preflight** (#352). `scripts/preflight.py` — is this deployment actually wired for a
  real-source, GPU-backed, traced run? Every dependency fails silently and in the reassuring direction:
  `RUNPOD_ENDPOINT_ID`/`RUNPOD_API_KEY` set but `ACP_VISION_PROVIDER` unset leaves `choice` defaulting to
  "ollama", so vision keeps working on the local CPU floor with no error and the only symptom is that it is
  slow; `ACP_AZURE_CLIENT_ID` unset hides the Connect Microsoft button, which reads as "SharePoint is not
  part of this build"; Langfuse unset makes every `lf.*` call a no-op by design. Answers in three states —
  PASS (verified), WARN (configured but unverified, deliberately off, or not checkable here), FAIL
  (configured and wrong) — and only FAIL exits non-zero, because a gate that trips on WARN gets disabled.
  Two checks carry it: the vision provider is *resolved* through `active_vision_provider()` rather than
  inferred from the env (so it also catches an admin `ai_vision_provider` override), and the tracing phase
  lanes are checked for a **caller**, not for the function — which is exactly how the #343 Discover gap read.
  `SP_SCOPES` are read out of `sharepointScopes.js` rather than restated, so the preflight cannot pass while
  the app asks for something else. Offline by default (CI-safe); `--live` reaches RunPod and emits a probe
  trace. No secret is ever printed.
- **Moved the vision lane off RunPod onto an in-tenant Azure GPU, and fixed the switch that silently used
  the CPU** (#405). Two things, one arc. `set_integration_env.sh` gains a GPU group: the live deployment
  had both RunPod vars correct and the endpoint warm, yet every scan ran on the local CPU floor because
  `ACP_VISION_PROVIDER` was `'ollama'` — `active_vision_provider()` defaults to ollama, so that switch
  decides whether the credentials are consulted at all. All three now move together and an endpoint id
  without a key is refused (that combination looks configured and uses the CPU — worse than
  unconfigured). `gpu_up.sh` moves the lane in-tenant: Ollama on an ACA GPU workload profile in acp-app's
  own environment, internal ingress, scale-to-zero, no code change (the existing ollama lane via
  `ai_base_url`); RunPod was a personal account standing in while Azure quota was approved, so retiring
  it is the point. Azure-only means no fallback, so switch-over is gated on a real generation from a
  replica of the calling app, not on the container reporting Running. `Matrix-Note: none` — deploy
  tooling only.
- **Resolve the ACA GPU SKU from the region instead of hard-coding it** (#414). `gpu_up.sh` failed its
  first real run — `Workload profile type 'NC8AS_T4' is invalid`: two mistakes on one line.
  `--workload-profile-name` (an operator-chosen label) and `--workload-profile-type` (an Azure SKU
  string) are different fields and the script passed the same value for both, and that value was a guess
  at a SKU. The fix is not a better default — GPU availability and SKU strings vary by region, so any
  baked-in constant is wrong somewhere — so the script resolves the environment's region, asks `az
  containerapp env workload-profile list-supported` what that region offers, and passes a real GPU entry
  as the type; a region with no GPU SKU now says exactly that and prints what it does offer.
  `Matrix-Note: none` — deploy tooling only.
- **Made the GPU-vision preflight aware of the ollama-on-GPU path, and probe the model** (#450). `check_gpu`
  was RunPod-serverless-only (ADR 0022 era), but since #405 the GPU runs as `ACP_VISION_PROVIDER=ollama`
  pointed at the Azure GPU host — so the old check had two pilot-visible gaps. (1) It reported today's
  **correct** production config as broken ("the GPU provider is NOT what a scan will use"); now ollama
  pointing at a remote GPU host (zone ≠ local) reads PASS, and the local CPU floor FAILs only when RunPod
  was configured and we fell back to it (the ADR 0022 trap). (2) On `--live` it probed only RunPod health,
  leaving the ollama/GPU path with no reachability + vision-model probe — exactly the #302 failure, where a
  reachable endpoint's baked vision model was shadowed by the container VOLUME and produced nothing for 45
  days with no error. A new `_probe_ollama_vision` reuses the runtime's own `ai.vision_unavailable_reason()`,
  so preflight and a real scan agree. `Matrix-Note: none` — deploy/preflight tooling only.
- **Surfaced SMB source readiness on `/readyz`** (#487). `describe_smb_readiness()` (config-only, no network)
  already answered "can an SMB scan even be attempted?" but was reachable by no route, so the guard it was
  written to be — a health check / Content-Sources surface that fails with a clear reason instead of starting
  a scan that returns an empty estate — never ran. Wired into `GET /readyz` as an informational
  `sources.smb` block, imported lazily (as the scanner does) and defended so a source probe can never 500
  `/readyz`. Deliberately **not** folded into `degraded`: a deployment that scans only Drive/SharePoint
  legitimately has no SMB config, so an unconfigured SMB source must not flip `ready`. Touches
  `api/routes/system.py` + a readiness test — not RULE_PATHS.

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
- **Review-card copilot — re-steer a draft, see the escalation path, honest empty state** (#367). The
  refine palette (Shorter / More detail / Regenerate, #131) gains four steers — Mention the numbers ·
  Ignore colours · Professional tone · Plain language — each re-asking the vision model through the
  existing draft path (`ai._vision_prompt` taught the new keys so the buttons steer rather than no-op).
  The card surfaces the transparent local→cloud escalation path ("local attempted → no grounded
  description → escalated to {provider} → grounded") instead of showing the failed local attempt as a
  dead end, and when authoring is genuinely manual the empty state says *why* and links to Settings →
  AI Providers rather than a raw "Ollama not running". Rides #356's OpenAI/Anthropic adapters. Frontend.
- **Backend so the copilot reads real data, not a proxy** (#378). `/ai/suggest` now runs the same
  acceptance-gated cloud escalation the remediation path already had and forwards the honest provenance —
  `provider`, `processing_zone`, the numbered `escalation` steps, and measured `cost_usd` — on the vision
  draft. A non-admin `/ai/status` signal (`cloud_enabled` / `cloud_provider` / `cloud_zone`, from the SAFE
  provider view, never the key) lets the empty state name the fallback without admin rights. On the keyless
  build `cloud_vision_provider()` is `None`, so it is a no-op and nothing leaves the box. Not RULE_PATHS.
- **Card switched off the ledger/zone proxy onto those fields** (#382). The escalation numbered-path now
  renders from the `/ai/suggest` response (`escalationFromDraft`) and the empty state reads `/ai/status`'s
  `cloud_enabled`; the `ai_calls`-ledger derivation is kept only as a fallback for cards pre-drafted at scan
  time (no live `/ai/suggest` call), so the two cannot diverge. Closes the copilot loop end to end:
  UI (#367) → gateway adapters (#356) → backend fields (#378) → UI reading them (#382).
- **Workflow-status top tabs backed by real pipeline state** (#366). The inbox's queue tabs now track
  where each finding sits on the journey Inbox → In progress → Ready to validate → Done (plus Blocked) —
  a second lens on the same findings, distinct from the remediation-lane taxonomy (which answers "what
  kind of fix", not "where in the pipeline"). `workflowStatusOf` derives the stage purely from real state
  (the finding's status, its lane, the recorded decision; ADR 0016), never an invented flag: a rejected AI
  fix awaiting triage stays in **Inbox**, not In progress, because its action is still "Mark as assigned" —
  nobody has started it. The old lane-based tab helpers are kept for the lane views.
- **The workspace footer lights each finding's live workflow step** (#370). The sticky Show → Review →
  Verify guide was decorative — drawn identically for every finding. `workflowStepIndex` maps the selected
  finding's stage onto the three steps so the footer lights the live one, ticks off the steps behind it,
  and dims what's ahead. `activeStep` defaults null, so the footer renders exactly as before wherever the
  step isn't supplied; the active step carries `aria-current="step"`.
- **Retired both duplicate decision surfaces — the inbox is now the single place to decide** (#389, #394).
  The Remediate tab still carried two extra decision surfaces below the guided inbox, both writing the same
  `decisions` map the inbox owns: a file-level "Documents to remediate" accept/reject/modify table, and a
  bulk "Remediation plan" band ("Auto-fix N" / "Accept full plan" + the plan-card grid). #389 removed the
  table and the code only it used (`editing`/`decide`/`undo`, and the orphaned `ACTIONS`/`ETA_OVERRIDE`/
  `PRI`/`priTier`/`priWhy` helpers); #394 removed the band (`plan`/`planCards`/`autoFiles`/
  `batchAutoRemediate`/`acceptAll`/`pending`/`humanCount`, the now-dead `ACTION_DESC`, and the
  `REC_STYLE`/`fmtEffort`/`EFFORT_BASIS`/`recommendationSummary` imports). −69 and −71 lines. Every
  accept/reject/modify now happens in one place; server-side "remediate everything" (hero CTA + runner) is
  untouched — it always ran the whole remediable set and never read the file-level decisions. Two
  source-text contrast/effort guards that asserted on the band were updated (the dim-guard is now three
  sites, not four). Landed after #385 promoted `frontend-v2/` to be the live `frontend/`; verified in
  vitest (2002–2004 pass), not the browser preview.
- **Renamed "AI Work Inbox" → "Review queue" across every surface** (redesign spec R4 §3, the last named
  R4 remainder). The old name described how the work was GENERATED, not what the operator must do with
  it; whether a finding carries an AI draft is an attribute of that finding, shown on its card, and not
  the identity of the queue it sits in. Five user-visible strings changed — the Remediate section `<h2>`
  and its ProgressRail step, the global bell's heading plus its `aria-label`/`title`, the Review Center
  dialog's title and accessible name, Publish's "approve them in Remediate → step 3 · …" hand-off, and
  Upload's step button — plus ~25 comments and CSS section headers, because leaving the maintainer's copy
  of a retired term behind is how a rename half-reverts one component at a time.
  `reviewQueueNaming.test.jsx` pins it in two lanes that do not substitute for each other: a DOM case
  mounting ReviewCenter (the accessible name was the one place the old term could have survived unseen)
  and a source sweep over every `.js`/`.jsx`/`.css` in `frontend/src`, self-excluded and asserting it read
  >100 files first so it cannot pass by looking at nothing. Verified by mutation — reverting the Remediate
  heading alone fails both lanes. Nothing asserted any of these strings before, which is why a rename the
  spec called "coordinated work, not just the section header" had sat open. Frontend, not RULE_PATHS.
- **Dropped the ProgressRail — one navigation system on Remediate, not two** (redesign spec R4 item 1,
  which closes R4). The rail rendered Scan › Assess › Remediate › Review queue › Verify › Publish across
  the top of the page. Every state it showed is said better, and closer to the work, elsewhere: Scan and
  Assess were hard-coded `'done'` (constants, not state); Remediate is the hero line; the review count is
  the section's own sentence and progress track — the very count #272/#273 deduplicated to one dominant
  statement, of which the rail was a fourth copy; Verify is the `rem-verify` RemSection, whose
  `<VerifyState>` carries state/percentage/remaining/ready where the rail carried one of three words; and
  Publish is the hero's primary CTA plus a top-level tab. **What made this safe now rather than when the
  spec was written** is that the contextual status the spec asked for in its place has since been built —
  #366's workflow tablist inside RemediationInbox and #370's footer lighting each finding's live step.
  Deleting the rail before those existed would have removed a wayfinder and put nothing there.
  `remediateNavigation.test.jsx` pins the claim the change actually makes: each case pairs "the rail is
  gone" with "its replacement is still here", because asserting an absence on its own passes just as
  happily if the whole page is gone. It also sweeps the stylesheet — orphaned CSS for a deleted component
  is how a removed element comes back, since the next person finds `.progressrail` styled and assumes it
  is live. Verified by mutation in both directions: breaking the Verify replacement fails the Verify case,
  re-adding the CSS rule fails the deletion case. One assertion in `reviewQueueNaming.test.jsx` pinned the
  rail's renamed step and was dropped rather than loosened — the line no longer exists, so any weakened
  form would have passed vacuously. Frontend, not RULE_PATHS.
- **Rebuilt the Remediate workspace as a guided master/detail queue — R4 PRs 1–4** (#404, #408, #412,
  #415; `docs/remediate-redesign-spec.md`). With the ProgressRail gone, the redesign's workspace half
  landed in four sequenced PRs. #404 (PR1) fixed a before/after flag bug and deduped a noisy review
  queue. #408 (PR2) reshaped the inbox into a **two-column** workspace — a queue column beside a detail
  workspace — folding the document preview into the detail pane's Evidence section (a standalone third
  pane "sat empty for every finding", so it was merged in rather than shown hollow). #412 (PR3) retired
  the ambiguous bare **"Reject"** for the specific outcome it performs ("Reject & handle manually"),
  added **"Defer"** as one set-aside vocabulary across both the AI and manual lanes (the app tracks no
  assignee, so "assigned" over-promised), showed the verification path (Written → Re-scan → Certified)
  only **after** a fix is saved rather than as a bare "Resolved", and compacted three stacked
  queue-header rows into search+sort plus status tabs. #415 (PR4) added an **editable** proposed-value
  field: the reviewer adjusts the exact text ACP will write and the primary action flips "Apply fix" →
  **"Save edited fix"**, carrying `d.value` through Remediate's existing `act(id, kind, editedValue)`
  path (draft resets per finding, so an emptied field never applies a blank fix). Left out of PR4 — a
  persisted "Not applicable" state: the backend folds `not_applicable` into
  `not_automatically_assessable` for v1 and the HITL vocabulary is approved/rejected/skipped only, so a
  frontend-only N/A would not survive a refresh (its own backend change). Frontend, not RULE_PATHS.
- **First-class "Not applicable" (out-of-scope) decision — R4 PR5** (#422; `docs/remediate-redesign-spec.md`).
  Landed the persisted N/A state PR4 deferred, backend + frontend. The design decision was to REUSE the
  existing per-finding `resolution` mechanism (how a `decorative` / essential-logo exception already
  resolves a finding), not a new HITL status — a new status would strand every file that used it, since
  `mark_file_compliant_if_reviewed` requires every row `approved`. So N/A resolves as status `approved` +
  resolution `out_of_scope`: it writes no value, persists on the row (survives a refresh, keeps the finding
  out of the queue) and is recorded verbatim in the audit log. Lifted the v1 folding in
  `accessibility_status.py` — `not_applicable` is now a real reported bucket, sourced from the rows'
  resolution and pulled out of BOTH `needs_review` and `in_scope`, so the five-bucket identity still holds
  and (the deliberate reporting choice) an N/A finding LEAVES the coverage denominator, so the reported %
  rises, matching how the WCAG matrix already excludes N/A cells. Frontend: a "Not applicable" action in the
  Remediate inbox and on `EvidenceCard`; the model treats it as resolved → Done; `Remediate.act` now
  forwards the resolution (PR3/PR4 had been dropping it). Not RULE_PATHS — all four backend checks pass, no
  Matrix-Note. Backend 3093 passed (+ new N/A-bucket identity and `out_of_scope` route tests); frontend
  1842 (+ inbox action, model resolved→Done, act-forwards-resolution). Shipped after a rerun cleared a
  tesseract apt-mirror infra flake, not a test regression.
- **Zoom control + grounded fix callouts in the Document preview** (#416). Brought `RemediationPreview`
  closer to the mockup's preview pane, adding only what real finding data can back (ADR 0016): a
  UI-only zoom (−/100%/+, 50–200% in 25% steps, purely presentational — fetches nothing), and a small
  "✓ <what changed>" / "Re-scan cleared" callout carrying the finding's **own** applied `after` value,
  shown only when the finding records a real applied/verified state — a bare proposal gets no callout,
  and there is never a stock "Text color updated". Deliberately omitted: the mockup's "Page N of M"
  pager — the finding model carries only its own `finding.page` and there is no document page-count or
  multi-page render model, so faking "Page 2 of 8" would be fabricated UI. Frontend.
- **Persisted a per-file assignee — the backend for "Assigned to me"** (#417). Added
  `assessment_policy.assignments(decisions) → {file: assignee_email}` and `files_assigned_to(decisions,
  email) → frozenset` (re-exported from `store`), reusing the existing `scan_decisions` table with a new
  `kind='assignee'` rather than a new table; the scans route's decisions allow-list is widened to accept
  it. The frontend "Assigned to me" filter is the follow-up that reads these. Under RULE_PATHS
  (`api/assessment_policy.py`) → `Matrix-Note: none`; 7 tests.
- **Split / Stacked / Focus workspace layouts + resizable panes** (#427). The three-pane guided work
  queue (#418) had one fixed arrangement; this adds an Outlook-style layout toggle on the
  Guided-remediation header that reflows the two workspace panes beside the inbox — **Split** (side by
  side, default), **Stacked** (preview below the guided pane), **Focus** (preview hidden, so a text-only
  fix gets the whole workspace). Named Split/Stacked/Focus deliberately, **not** "Side by side": the
  preview already owns a Before/After/Side-by-side control (the document diff), and two controls two
  inches apart must not say the same words for different things. Panes are resizable via `role="separator"`
  dividers — inbox↔workspace in every layout, plus one between the workspace panes (vertical in Split,
  horizontal in Stacked) — each of which **drags with the pointer AND nudges with Arrow keys**, the
  ARIA-required keyboard path that also makes the resize verifiable in jsdom (no layout there, so pointer
  math no-ops on a zero-size rect). Layout choice and pane sizes persist in `localStorage` keyed globally —
  a workspace preference set once, unlike the per-scan search/filter state in `sessionStorage` — with every
  storage access guarded against private-mode throws. The "Page N of M" pager stays omitted (no
  document page-count data; #416's reasoning), and a wide stacked preview is exactly where a faked one
  would look most real. Frontend, not RULE_PATHS; 5 new tests, full frontend suite green (2055). A real
  test bug was fixed en route — an un-awaited async `unmountAll()` leaked teardown into the next test.
- **Defaulted the workspace to the two-column Stacked layout** (#430). The Split/Stacked/Focus toggle
  (#427) shipped defaulting to the side-by-side three-pane; the two-column Stacked workspace is the one
  the redesign was built around and the reviewer preferred, so it is now what a reviewer sees first.
  One-line default flip (`readLS('layout', 'stacked')`); anyone who prefers side-by-side switches and the
  choice persists.
- **Reworked the review states into a 5-stage taxonomy and fixed a live count double-count** (#434;
  operator feedback). The top tabs conflated two overlapping lenses, so a scan showed a tab reading
  "Ready to validate 25" while the progress line read "25 of 25 resolved" — the same acknowledged
  auto-fixes counted twice — and review work could sit in a stage the default tab never surfaced,
  dead-ending verification. New stages, each with one precise meaning and partitioning the queue: **Needs
  review / Manual fixes / Awaiting validation / Blocked / Completed**. An unacknowledged auto-fix now
  waits in Needs review (the reviewer still confirms it), moving to Awaiting validation once acknowledged;
  the progress line reads "N reviewed" (a decision recorded), never "resolved", so an approved-but-not-
  re-scanned fix is never both resolved AND awaiting validation. Honesty held (coordinated with the state
  model's owner, ADR 0016): Awaiting validation stays distinct from Completed (the UI never claims done
  before the re-scan earns it); `not_applicable` stays terminal and out of the coverage denominator;
  "in progress" is gone as a tab but assigned/deferred route honestly into Manual fixes. Frontend, not
  RULE_PATHS; suite green (2060), new tests pin the double-count fix and one-tab-per-finding.
- **Redesigned the right pane around the reviewer's decision, with adaptive, grounded evidence** (#433;
  operator feedback). The pane read like an engineering evidence record — hex values and ratios that prove
  the rule passed but don't let a normal reviewer judge whether the document still LOOKS acceptable. Reordered
  to **Your task → Before/after → What ACP changed → sticky Decision → collapsed Supporting details**
  (the Issue→Proposed→Verified strip moved into the supporting section). Fixed the copy bug where a 1.4.3
  contrast finding with no coordinates was labelled "structure or metadata": nature is now classified from
  the CRITERION (1.4.3 is visual), not from whether geometry was attributed. Evidence adapts to the finding
  type, and for contrast renders a grounded before/after — sample text at the real old/new colours with the
  ratio COMPUTED from those real hexes (the WCAG luminance formula), returning null rather than a fabricated
  "4.5:1" when a colour/background isn't recorded. The pptx/xlsx element crop (`Thumbnail.jsx`, real bounding
  box) is reused where geometry exists; docx/pdf get the grounded colour before/after, never a faked crop or
  page pager (ADR 0016). Auto-fix rows get an obvious "Approve ACP's fix" / "This looks wrong" — the latter
  honestly labelled a flag, since there is no backend undo to revert an applied fix. Frontend; suite green (2089).
- **Made the inbox rows scannable — issue-led, WCAG pill, quiet lane state** (#437; operator feedback). The
  rows repeated a loud coloured lane pill ("Review automatic fix") on every row, burying the issue. The row
  now leads with the ISSUE, the WCAG SC number is the one compact pill, and the remediation state is demoted
  to quiet text (the lane's colour is already carried by the 4px rail). Frontend; suite green (2091).
- **Aligned the "N need review" hero with the Needs-review tab so the two can't diverge** (#435). The
  Review-queue hero counted a different population than the new Needs-review tab (it excluded the auto-fixes
  the tab now includes) — a milder form of the same dead-end #434 fixed. The hero now derives from
  `matchesWorkflow(f, 'needs-review')` over the same inbox queue, with a source-match guard so it can't
  regress to a raw `queue.length`. The top-nav HITL bell was left as a deliberately distinct global metric
  (the human-authoring queue). Frontend.
- **Aligned the top-nav bell to the same needs-review count, closing the consistency across all three
  surfaces** (#442). The nav badge (`App.jsx` `hitlCount`) was fed `onHitlCount(queue.length)` — the raw
  human-authoring queue, which excluded the unconfirmed auto-fixes the tab and hero now count — so it read
  a smaller, inconsistent number. It now reports `reviewCount`, the exact `matchesWorkflow(f,
  'needs-review', inboxDecisions)` value the hero uses, so bell = hero = Needs-review tab. The
  `onHitlCount` effect was relocated below `reviewCount`'s definition and keyed on it, so the badge
  refreshes when a decision or auto-fix acknowledgement changes the count (the old `queue.length` keying
  missed those). A source guard blocks a regression to `queue.length`. Cross-session hand-off from the
  state-model owner's session (who owned the `onHitlCount` seam but was blocked). Frontend; suite green (2092).
- **Stopped claiming every fix was applied over files nobody could read** (#479). From production: a drawer
  read "Could not analyse — file unreadable" while the Review queue on the same screen read "All clear" and
  "every fix was applied automatically." The counts were correct (the HITL queue *was* empty), but a file
  that could not be opened had no fix applied — **skipped was reported as done**. The copy moved into
  `reviewQueueCopy.js` and the caveat is now appended to whichever base sentence renders (rather than living
  inside one branch of a ternary — the defect's shape): "All clear" is **withheld** rather than qualified,
  "every fix was applied automatically" is **replaced** rather than decorated. The count is gated on files
  that were **opened and failed**, not on every non-certifiable file — an ADR 0020 Discover-only row means
  "nobody looked yet." Does not fix *why* those files are unreadable (an ingest failure, still open).
  Frontend, not RULE_PATHS.
- **Said WHY a document failed, from the record — stopped guessing "unreadable"** (#483). The `#479` follow-up
  that closed the ingest half. `handlers` records the verbatim per-file exception (`scan.file_error`) and
  `GET /decisions` returns it, but the drawer showed a generic sentence: on 2026-08-19 "Could not analyse —
  file unreadable" was displayed over 22 SharePoint documents that had **never been fetched** (#481) — sending
  the investigation at the documents while the bug sat in download routing. Since `status='error'` is a
  catch-all over the whole download+analyse block, "could not *analyse*" claims a step that may never have run
  and "unreadable" blames a document that may be fine. The drawer now shows the recorded reason instead of
  guessing. Frontend, not RULE_PATHS.
- **"Assigned to me" inbox filter + assign action (wires #417)** (#482). #417's backend added a per-file
  assignee axis (`assessment_policy.assignments` / `files_assigned_to`, persisted as a `scan_decision`
  `kind='assignee'`) but nothing in the UI read or set it — the mockup's "Assigned to me" filter was unbuilt.
  Wired end to end, mirroring the triage plumbing: `App.jsx` holds a parallel `assignees` ({file: email})
  state hydrated from `getDecisions(kind='assignee')` and persisted via `saveDecisionsBatch`, an assign
  action on the row, and the filter over the inbox. Frontend, not RULE_PATHS.
- **Keyboard + screen-reader accessibility for the review queue** (#484). An accessibility-remediation tool
  should itself be operable by keyboard and screen reader; the queue was mouse-first (rows click-only, no
  spoken feedback on auto-advance). Adds **roving tabindex** on the rows (one Tab lands on the selected
  finding; Up/Down or j/k step selection, Home/End jump to the ends, focus following the move — the whole
  queue worked in one tab stop, no mouse) plus live-region announcements when the workspace auto-advances
  after a decision. Frontend, not RULE_PATHS.
- **Adaptive evidence for alt-text and metadata findings** (#485). #433 gave *contrast* findings a grounded
  before/after; every other finding fell back to a generic value diff. Adds two purpose-built,
  **real-data-only** renderers — the two finding types where the backing data actually exists — leaving the
  structural ones (heading outline, reading order, table headers) on the honest generic note until the finding
  exposes document-structure data (ADR 0016, same tier as the page pager). **Alt text (1.1.1):** the affected
  image beside its old vs new alt — the real `Thumbnail` render, cropped to the flagged object only where a
  bounding box exists (the plain page otherwise; it never invents a location), with the finding's own
  before/after alt strings. **Metadata (2.4.2 title / 3.1.1–3.1.2 language):** the real before→after value,
  which also replaces the preview's generic "structure not extracted" note *for those findings only*. Built
  fresh in `frontend/` (the dead `frontend-v2` branch was not revived). Cross-session coordinated with this
  session on scope, the stale-branch read, and the honesty tier. Frontend, not RULE_PATHS.

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
  the handful sampled; a paginated per-file export was a separate follow-up (#303), since delivered (#332).
- Owner / size / sharing on the drill-down, sortable for triage: `size`, `owners`, `shared`
  added to `DRIVE_FIELDS` (same list page, no extra call); externally shared files get a
  SHARED badge; sorts biggest-first, shared-first, or by name — the three lenses that matter
  at 30k-file PHI-estate scale. Missing metadata degrades to null/false, never a wrong value (#304).
- Wired the funnel's Published + Human-review stages, which had been stuck showing 'pending' (#327).
  Stages 4–9 now derive from real progress state instead of a placeholder, so the estate funnel reads
  end-to-end (discovered → … → remediated → human-review → published) rather than trailing off into
  guessed zeros. Closes the Open item below that flagged these two stages as unthreaded. Another
  session's change, recorded here as it landed in this window.
- Paginated per-file estate API + CSV export (#332) — the follow-up #303 named. The whole-estate
  inventory (all types, full metadata) is now exportable per file, not just as counts + a capped
  sample, so a hospital can pull the complete list. Delivers the missing half of the three-denominator
  view (the per-file estate, beside the aggregate). Another session's change, in this window.
- Local source walks the nested tree with filesystem metadata (#325) — recursive discovery for a local
  source now descends subfolders and captures per-file metadata, matching the Drive/SharePoint inventory
  shape for local-mounted content. Another session's change, in this window.
- SharePoint estate samples carry triage metadata, at parity with Drive (#345) — a review follow-up to
  another session's SharePoint three-denominator summary (#337). That summary reached parity on the funnel
  *counts* but its drill-down samples were blank: the estate rows carried only {id, name, mimeType}, and
  `estate_inventory._sample_meta` reads a Drive file object's `owners[]`/`size`/`shared`/`modifiedTime`, so
  the #304 owner / biggest-first / externally-shared lenses came back empty for SharePoint. #345 maps the
  Graph item's own field names into those keys (and dedupes the owner extraction the scannable path
  repeated). A second review finding — ACP output not excluded by provenance — was verified a non-issue and
  left unchanged: `provenance.is_acp_generated` reads a Drive property a Graph item never carries, and
  SharePoint already excludes ACP output by folder (mirror + archive in `skip_folders`).
- Covered the SharePoint multi-library truncation branch (#346) — the estate-summary tests all exercised
  OneDrive (a single target), leaving the arm that flags a floor when a later document library is never
  reached (`i < len(targets) - 1`) untested; a regression could make a multi-library site silently report
  `truncated=false`. Two tests now drive a site with two libraries — cap hit in the first (second never
  fetched → truncated), and both fully listed (→ not truncated). Test-only.
- **Made the funnel's remediation-eligible stage a finding-level denominator** (#407). The coverage
  funnel fed its "remediation-eligible" stage from `needFix` (documents carrying any remediation action
  — the Remediate-tab count), which is not the honest three-denominator meaning. Format-level
  eligibility equals assessable (every supported format has some fix lane), so the real narrowing is at
  the **finding** level: a document is remediation-eligible when it carries ≥1 finding whose lane in that
  file's format is auto (deterministic) or ai (AI proposes, human approves). A document whose every open
  finding is human-only (reading level, PDF re-tagging) is assessable but **not** remediable, and the
  funnel now says so — `assessCoverage.remediationEligibleCount` computes it from the authoritative
  `remediationIn` lane map. `needFix` is unchanged for the "need remediation" metric. 10 new tests.
- **Surfaced the coverage funnel on the Discover tab, from the same helper as Overview** (#413). The
  three-denominator funnel (discovered → assessment-eligible → remediation-eligible) rendered only on
  Overview, but discovery happens on Discover — so an operator scanning a drive could not see how much of
  what they just scanned is eligible until they navigated away. The per-file progress computation was
  extracted from `Overview.jsx` into a shared `estateProgress.js` (`estateProgressFromFiles`) and
  `EstateCoverage` now renders on Discover from the same inventory + helper, so the two tabs can never
  disagree; guarded on `discovered > 0` so it never shows empty.
- **Fixed a live regression where every local scan crashed** (#411). `handlers._scan` and the
  sync/in-process `routes/scans.py` paths call `run_scan(..., inventory_out=inv)` to persist per-file
  inventory the way the fan-out path does, but `run_scan`'s signature never gained the parameter — so
  **every** local / in-process scan raised `run_scan() got an unexpected keyword argument
  'inventory_out'` and failed outright on the deployed app, while CI stayed green because no test drove
  that path with the argument. Added `inventory_out` and threaded it into the `_list(...)` call that
  already supports it; a regression test now pins both the signature and the pass-through. `Matrix-Note:
  none`.

---

## Feature: Discover & Assess lifecycle rules · #4618

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
- **Per-file WCAG scope: the resolver + rule store** (#326, "C4a"). `api/scope_resolver.py` — pure logic
  (mirrors the disposition seam): a scope rule targets files by folder / owner / department and assigns a
  Core-17 subset; a file's effective code-set is the UNION of matching rules' codes UNLESS a higher-priority
  override replaces it (deterministic tie-break by rule_id, AC-09). No rule matches → the caller's default
  (the global Assess selection), so rules only ever refine, never silently empty the scope. `scope_rule`
  table + accessors, classified a RESET config-survivor (a rule, not scan output) — the exact trap #312
  caught for file_tags, avoided by declaring it up front.
- **Per-file scope resolved at the scoring gate** (#330, "C4b"). `assessment_policy.resolve_file_scope` is
  the single seam: it returns the global scope UNCHANGED (same object, incl. None = unrestricted) when no
  rule targets a file — so a scan with no rules is byte-for-byte pre-C4 — and narrows to the resolved
  code-set on a match, keeping each code's lane from the global scope or falling back to `RULE_FORMATS`.
  Frozen, not live: `_scan_discover` freezes the enabled rules into `scan_runs.scope` beside `scan_scope`,
  and `store.scope_for_file` is the ONE method both the score and trace paths call — threaded into
  `save_file_result`, `analyse_and_assess` and `rescore_reused` in lockstep, so an admin editing rules
  mid-scan can never make a file's score and its stored traces disagree (the frozen-scope discipline
  `scan_scope` already follows). The local monolithic `run_scan` path stays on global scope — internally
  consistent, a documented v1 boundary; department-selector rules do not resolve yet (inventory carries
  path/owner, not department).
- **Scope-rule CRUD API + scope-aware eligibility** (#329, "C4c"). Owner-gated `api/routes/scope.py`
  (`GET/POST /scope/rules`, `PATCH`/`DELETE /scope/rules/{id}`, `GET /scope/selectors`), every mutation
  validated against Core-17 before persisting (400 with the message on a bad rule). `GET
  /assess/eligibility/scoped` resolves each discovered file's effective code-set from the enabled rules and
  counts it eligible when its format has a lane for any resolved code — `{discovered, eligible, by_format,
  rules_applied}`, zeros on an empty estate; the pre-C4 `/assess/eligibility` is left untouched.
- **Scope-rule editor UI** (#331, "C4d"). `ScopeRules.jsx` — a create form (selector, per-selector-labelled
  value, Core-17 "code — name" multi-select, priority, override + hint, enabled), a priority-desc rule list
  with an OVERRIDE badge and enable/disable + delete, and the scope-aware eligible-file count refreshed on
  every change; wired as a panel beside `AssessScope` (untouched). Completes **AC-09** — WCAG selections
  scoped by folder/owner/department with deterministic precedence.
- **Disambiguated WCAG scope rules from lifecycle rules** (#338). A parallel session's #328 added a
  per-source "Manage" drawer with Scope / Rules tabs at the same time C4d landed a "Scope rules" editor —
  two different systems whose names collided (the drawer's Rules tab is lifecycle/disposition tag-archive-
  deletion, its Scope tab is discovery *visibility*; C4d is per-file WCAG assessment scoping). Not
  duplicates — merging would have been the regression — so the reconciliation names them apart: the editor
  is now "**WCAG scope rules**" with a line separating it from lifecycle rules, and the drawer's Rules tab
  points to Assess → WCAG scope rules for the WCAG axis. #328's tab labels and tests untouched.
- **Closed the `file_tags` RESET-classification duplicate** (#318). #312 and #313 had each added `file_tags`
  to `_ANALYTICS_TABLES` (two sessions fixing the same miss), leaving it listed twice — harmless but untidy;
  #318 drops the duplicate. Closes the cleanup flagged on the RESET-fix bullet above.
- **Source operations panel** (#328). The per-source drill-down was a compliance dashboard on a
  connections surface — a scored donut, a top-flagged-documents list, an "agent" paragraph — under the
  subtitle `undefined · 0 docs · agent: undefined`, rendered directly beneath a card the same page had
  badged **Healthy**. Two quiet failures, not missing features: the OneDrive card is a hard-coded
  CONNECTABLE row (`sp-root`) that nothing joined to its backend source row (which arrives as type
  `onedrive` *or* `sharepoint` — Graph serves both from one connection), and the drawer filtered files on
  `f.source === selSrc.id`, matching that card id against rows keyed `sharepoint`, so the empty result was
  rendered as "0 docs" rather than as a lookup that found nothing. Replaced with **Manage &lt;source&gt;** —
  Overview / Scope / Rules / Activity — over a pure `sourceOps.js` where every number traces to a prop and
  an unavailable value returns `null` for the caller to render as *Not available*, never `0`: `folders` is
  null for a source that reports flat filenames, because "we don't know" and "there are none" are different
  claims about the estate. Overview's discovery outcome is a **partition** — every file in exactly one
  bucket, rows summing to the total on screen — with archive/delete candidates deliberately *not* counted
  as assessment-eligible, matching #320's exclusion. Scope keeps rule exclusions, permission denials and
  read failures apart; red is reserved for failed access, amber for anything awaiting a human. Both SPAs.
- **Inventory-grain new / changed / removed** (#343). `get_scan_diff` reads `file_records` — the *assessed*
  grain, which an ADR 0020 Discover-only run leaves empty until Assess — so wiring the panel to it would
  have reported "0 new · 0 changed · 0 removed" for precisely the runs it is about. `get_inventory_diff`
  reads `scan_inventory` instead, keeping three pairs apart: `removed` vs `not_listed` (a moved listing
  boundary or a truncated listing means absence is not deletion — the same lesson `get_scan_diff` learned
  when a narrowed scope reported "45 documents disappeared"), `changed` vs `indeterminate` (md5Checksum is
  absent for native Google Workspace files, so checksums cover binary uploads and nothing else), and
  `no_baseline` vs a quiet estate (the line is omitted, never rendered as three zeros). The baseline is
  per-source via `previous_run_for_source`: `list_scans` spans every source *and* filters to
  `completed_at IS NOT NULL`, which hides an unassessed Discover run — the run this diff exists for.
- **Discover-phase tracing** (#343). `lf.discover_span` existed and read like the phase was traced; its only
  caller is `_analyse_and_persist_one`, on the analyse path, which under ADR 0020 runs at *Assess* time.
  `_scan_discover` called nothing, so a Discover-only run produced no Langfuse trace at all — and the estate
  rows Discover inventories and never opens were invisible permanently, because nothing later opens them.
  Adds a run trace (counts carried *with* the listing boundary and the truncation flag) and per-file Discover
  spans from the inventory, capped with the cap **stated** beside `files_inventoried` rather than silently
  applied. Emitted after the inventory is persisted and wrapped, so a Langfuse outage costs tracing only.
- **Rule match counts and review queues** (#357). The Rules tab listed each rule's predicate but not how many
  files it matched. `POST /disposition/policies/{id}/preview` evaluates over `list_all_documents()` — the
  *estate-wide* table — so rendering `would_match` under a per-source heading would be a correct number
  saying something false. Rather than reimplement the predicate client-side (a second source of truth
  diverging from `disposition.matches`), the split filters the preview's own returned rows by
  `documents.source`: "2 matched in OneDrive · 5 across all sources". A preview with a total but no rows
  reports `null`, not `0`. Previews fire on tab open and sequentially — each is a full-table scan in Python.
- **Pending-approval queue, recording-only** (#360). ADR 0003 Phase 3 has had list/approve/reject since it
  shipped; v2 has had no UI for it since #319 dropped the Disposition panel, so an approval could be created
  and never actioned. Approve here **records the decision and touches nothing**, for two reasons that are
  facts about the code rather than preferences: `execute_action` supports Drive-backed documents only (a
  SharePoint row returns "unsupported source"), and ACP holds read-only scopes (`CAN_WRITE_BACK` is false),
  so a button claiming to move a file would describe a capability the deployment lacks. `approve?execute=false`
  is new (default unchanged); `'approved'` had to join the live set in `doc_has_disposition`, or the next
  execute run would re-propose a document whose approval was already recorded.
- **Lifecycle audit trail** (#365). The queue shows what needs a decision and cannot show what *was* decided
  — a rejected disposition was recorded and then invisible. Adds the append-only trail to the Activity tab,
  with the enrichment now shared with the queue (`_readable`): `disposition_audit` stores four ids and an
  enum, so the join supplies the document's source/path and the policy **name** — "archive sp:1 under p1" is
  not something an auditor can read back, and a deleted rule renders as "no longer configured" rather than
  falling back to its id. Each outcome states what it meant for the file beside the stored value, since
  `'approved'` alone does not say whether anything moved. `source` is also what makes the queue and the trail
  scopeable at all: the table has no such column, so an unenriched render puts the whole estate's history
  under a heading naming one source.
- **Create archival & deletion rules in Discover** (#383; Deva ask #3). The disposition rule engine —
  create/preview/execute over folder/path/modified-before predicates, candidate-first marking — existed
  backend-side, but the authoring UI had been dropped from Settings (#319) and was orphaned: no mounted
  screen could write a rule. Adds `DispositionRules.jsx` inside the Discover tab — a condition → action
  editor exposing the backend's `path`/`parent_folder`/`modified_age_days`/`modified_at` fields the older
  editor lacked; rules are created **disabled** and approval-gated, and "delete" is always the recoverable
  Drive trash. Frontend over the existing `/disposition/policies` API.
- **The default scan path evaluates the archival/deletion rules, not only the fanout path** (#384; Deva
  ask #4). Lifecycle-rule evaluation and per-file inventory persistence ran only inside `_scan_discover`
  (the durable fanout job). A **default** Discover — the in-process thread the UI uses, the `sync` path,
  and the monolithic `scan` job — called `run_scan` without `inventory_out` and never persisted per-file
  inventory or evaluated the rules, so an admin's archive/delete rule (now authorable via #383) was
  silently ignored on a normal scan, and the per-file inventory the Assess eligibility count reads went
  unpopulated. A shared `handlers.persist_discovery_inventory` (dedupe → `add_inventory` →
  `_evaluate_discover_lifecycle_rules`) now runs on every path; idempotent, candidate-first, never executes
  a Drive move/delete. `test_jobs`' `fake_run_scan` gained the `inventory_out` kwarg. Backend; not
  RULE_PATHS. Verified against a real venv — the helper unit test, an end-to-end worker test, a 183-test
  regression slice, and all three matrix/backlog/progress guards.
- **Assess ignores files flagged for archival or deletion — now a visible, controllable filter** (#375,
  #379, #381; Deva ask #6). The assess run already excluded archive/delete-flagged files by default
  (`LIFECYCLE_EXCLUDED_DEFAULT`), but silently — nothing in Assess said so, let a reviewer override it, or
  reflected it in the scope preview's counts. #375 adds an "Ignore files flagged for archival or deletion"
  checkbox (on by default, naming the four skipped statuses) wired to the existing `include_lifecycle_flagged`
  query param on `POST /scans/{sid}/assess`. #379 has `GET /assess/eligibility` report `lifecycle_excluded`
  and `lifecycle_eligible_excluded`, computed by a pure `wcag_codeset.lifecycle_exclusion` over real per-file
  `lifecycle_status` (no fabricated counts). #381 adds a "Queued to assess — archival/deletion excluded"
  stage to the scope funnel — exact when all document types are selected, a clamped bound when narrowed
  (the aggregate backend count spans all eligible formats). The sibling Assess filters Deva also asked for —
  document-type (#5) and WCAG-code (#7) — were already shipped in `AssessScope.jsx`, so were not rebuilt.
- **Made discovery metadata-only by default — download deferred to Assess** (#436; operator request).
  Discovery already read only metadata per source (extension/listing type detection, no byte-sniffing, no
  file opened), but the default pipeline continued straight into downloading + analysing each file. Now a
  scan lists metadata, classifies from it, persists the inventory, and STOPS — nothing is downloaded or
  opened until Assess is explicitly run. Implemented as a default flip of `_defer_analysis_to_assess()`
  (`ACP_DEFER_ANALYSIS_TO_ASSESS` "0"→"1", override preserved for the legacy full-scan); the monolithic
  `scan` job and the sync/background routes now delegate to the already-proven `_scan_discover` rather
  than teaching `run_scan` a partial mode, keeping blast radius minimal (`run_scan` untouched, so direct
  callers keep full-scan behaviour). Risk noted: API/script callers that POST-then-read results must now
  call Assess (or set the override); the UI already models Discover→Assess. Also aligned the frontend
  `startScan`/`startScanQueued` `pii` default arg `true`→`false` to match the real behaviour (PII scanning
  is opt-in and off by default at every layer). Not RULE_PATHS; backend suite green (the lone local
  failure was an env-only Ollama vision test, green on CI), frontend 2055.
- **Defaulted the baseline scan to skip nothing** (#443). The Scan-behaviour group had four toggles with
  `incremental` alone starting **on** — and it is the one toggle whose effect is invisible: an incremental
  scan that skips a file still reports a score for it, carried from the previous run, with nothing on screen
  distinguishing "scored now" from "scored last time". The group now starts uniformly off, so the scan a
  user gets without touching anything is the plainest one (nothing skipped, nothing inferred) and the
  toggles read as additions to a known baseline. Incremental remains available for fast re-scans once a
  baseline exists.

## Feature: Observability — AI tracing and cost (Langfuse)

The scan / assess / remediate lifecycle was already traced, but the AI calls themselves were recorded as
cost-less, detached spans, and one decision surface had no trace at all. An audit first established the
state — 18/18 PHI tests green, coverage broad, the debt quality rather than absence — then four fixes
brought AI-call fidelity up to date and two extended it to the newest surfaces. Every new field is a
count / token number / model id / zone / cost — never prompt, completion, note, or filename (the PHI
invariant the redaction tests pin).

- **AI calls are Langfuse generations, not spans, carrying model + tokens + cost** (#368, G1). Added an
  `lf.generation()` helper (no-op when disabled) and switched `trace_ai_call` to it; token counts come from
  the provider results. They were logged as `.span()`, so per-call token usage and cost never reached the
  trace — only the `ai_calls` DB table had them.
- **Those generations nest under the file's own trace** (#368, G2). They were top-level `ai:{surface}`
  traces grouped only by scan session, so a file's Discover/Assess/Remediate trace never showed its own
  model calls; now they hang on `_trace_id(scan_id, file)` when known, with session grouping preserved.
- **Provider / zone / cost carried into the trace** (#368, G3). `ai._trace_ai` already computed them for the
  `ai_calls` row but the `lf` signature dropped them at the boundary; widened so trace and ledger agree.
- **Remediation span carries fix / skip counts** (#368, G4). `remediate_span` recorded only the Drive URL;
  the per-rule applied/skipped counts already existed in `_remediate_file` and are now passed through.
- **Cloud-vision token usage surfaces as generation `usage`** (#372, N1). Widened `providers._result` and
  each adapter (Azure, OpenAI, Anthropic, RunPod, Ollama) to carry prompt/completion tokens, threaded
  through `ai.py` — so cloud-vision generations carry real token usage, not just cost.
- **The disposition / pending-approval queue is now traced** (#371, N2). `routes/disposition.py` was the one
  untraced decision surface; a new `trace_disposition_decision` (status / action / policy-id / `reason_chars`
  count / HMAC doc label) mirrors the HITL decision span at every point a disposition is recorded.
- **Per-file traces carry the document + assessment result, not an empty shell** (#403). Every trace in the
  Langfuse session view read "no input or output": `file_trace` set a name/tags/metadata but never
  trace-level `input`/`output`, and only the child spans carried data — which the session LIST view does not
  surface (the $0.00 cost is correct: deterministic local checks have no per-token cost). `file_trace` now
  sets `input` = {redacted document label, format}; a new `file_assessment_result` sets `output` = score /
  conformant / level / failing WCAG criteria + counts, called per file in `ensure_assess_trace`. Strictly
  structured (docs/audit-langfuse-phi.md) — no document content, no raw filename; a test asserts the data
  lands AND carries no free text.
- **Traces gain a PII flag, remediation status, and the full per-check breakdown** (#406). Extends #403's
  trace output with `checks` = the whole {PASS/FAIL/REVIEW/NOT_EVALUATED: count} breakdown (not just
  failures, from the `get_scan_traces` rows already fetched); `pii` = {flagged, types, findings, critical}
  where `types` are CATEGORIES (`us_ssn`, `email_address`) — the same `sensitive_data_types` the PII span
  already emits, never a value; and `remediation` = {remediated, written_back, published} booleans off the
  file record. New kwargs optional (backward-compatible); the category-not-value invariant is pinned by
  test, and the no-free-text / redacts-filenames guards stay green.
- **Upgraded the deployed Langfuse v2 → v3 so the Session view scales** (ops + #447). With #403/#406
  enriching every per-file trace, a real 44-document scan exposed the OSS limit: the v2 instance
  (`langfuse/langfuse:2` on a single Postgres) rendered every trace in a session at once and **hung** on
  large scans — individual traces opened fine, the aggregate Session view did not. v3 moves the trace
  store to **ClickHouse** (+ Redis queue, MinIO blobs, web/worker split), which is what scales the
  aggregate view. ClickHouse does not run reliably on Azure Container Apps (only Azure Files/SMB mounts,
  which it fights), so v3 runs on a dedicated **Azure VM** (`acp-langfuse-v3`, D4s_v3 + Premium disk) via
  docker-compose behind Caddy/TLS. Built alongside v2 and verified (health 200, `acp-compliance` project +
  same `pk`/`sk`, ingestion 207) before cutover; then `acp-app`/`acp-worker` `LANGFUSE_HOST` was repointed
  (host-only — the keys were re-seeded, so no app key change) and the Session view confirmed loading at
  scale on a live scan. Old v2 app deleted; its trace data (not migrated — deliberate start-fresh) still
  sits in the shared Postgres. **#447** adds `deploy/langfuse-v3/` (compose + provision/cutover scripts +
  a runbook) so the hand-provisioned migration is reproducible and reversible. No app code changed.
- **View a document's Langfuse trace INSIDE AccessOps, with no Langfuse login** (#454). The "📊 View
  trace" chips deep-linked to Langfuse, which meant a login — and verification against the live v3
  instance found the built-in "make the trace public" path does not give a usable no-login view on this
  build: the `public` flag works at the data layer (public trace → `200` unauthenticated, non-public →
  `401`), but Langfuse's own public *page* hangs at "Loading …" for a logged-out visitor and sends
  `X-Frame-Options: SAMEORIGIN`, so it can be neither deep-linked without a login nor iframed. So instead
  ACP fetches the trace server-side with its own keys (`lf.fetch_trace`) and renders it in-app: a new
  `GET /scans/{sid}/trace/file/{file}/data` returns a normalized, PHI-safe payload — the trace NAME is
  dropped (it carried the operator email) and observations are reduced to structural fields only (no raw
  input/output blobs) — and a `TracePanel` drawer shows the score, failing WCAG criteria, PII *categories*
  (never values), remediation status and the Discover→Assess→Remediate timeline. The per-file chips
  (review card, file drawer) open the panel; the whole-scan *session* view is left as a follow-up (a
  bigger, aggregate surface). Registered the `/data` route BEFORE the greedy `{filename:path}` catch-all
  so Starlette's first-match doesn't shadow it — the same catch-all already shadows the pre-existing
  `/exists` route, left as-is since the SPA tolerates it. Backend + frontend tests; not a RULE_PATHS change.
- **View a whole scan's traces INSIDE AccessOps — the session view (#459, follow-up to #454)**. The
  whole-scan *session* deferred by #454: the aggregate that hung Langfuse's own UI on large scans (the
  reason for the v2→v3 move). `lf.fetch_session` fetches the scan's Langfuse session with ACP's own keys
  and returns a PHI-safe per-file list + a scan-level rollup (documents / assessed / conformant / avg score
  / with-failures / with-PII) — trace name (operator email) dropped, worst-scoring documents first,
  unassessed last, the list capped with an honest `total`/`truncated` while the rollup still counts every
  file. `GET /scans/{sid}/trace/session/data` serves it; a `SessionPanel` drawer renders the rollup + one
  row per document, and clicking a row drills into that file's `TracePanel`. The session "📊 View traces"
  chips (Remediate, Assess runner, Overview, Queue) now open this in-app and were renamed off "…in
  Langfuse". **Also fixed a #454 shipping defect the live data exposed:** `TracePanel` rendered the wrong
  result shape — `failing_criteria` is a dict `{SC: count}` (not an array) and `pii` is `{flagged,
  types:[…]}` (not `{present, types:{}}`), so neither had shown on real traces; corrected the panel against
  the actual `file_assessment_result` output and fixed the SIM/fixtures that had reinforced the wrong shape.
  Backend + frontend tests; not a RULE_PATHS change.
- **Browser-verified the session view end to end** (no commit — testing, 2026-08-19). Drove the merged
  `origin/main` build in SIM mode and confirmed at the DOM: the Overview "📊 trace" chip opens the in-app
  `SessionPanel` (accessible name *"…inside AccessOps (no Langfuse login)"*); its rollup reads 3 documents /
  2 assessed / 1 conformant / 75 avg / 1 with-failures / 1 with-PII, with a document showing the honest
  *not assessed* state; clicking a row drills into the file `TracePanel`, which renders the corrected shape —
  failing criteria `1.1.1 ·1` / `1.4.3 ·3` (the dict that had shown nothing before the #454 fix) and PII
  categories `us_ssn` / `email_address` (no values). No console errors; no operator email in the UI.
  Verified via a standalone vite server from a throwaway `origin/main` worktree, because `preview_start` is
  pinned to the shared checkout — which is 47 commits behind and holds another session's uncommitted
  delivery-log work, so it was deliberately left untouched (see the "preview root" note in CLAUDE.md).

## Feature: Scan-run experience — live progress and transparency (Track A)

The scan progress panel rebuilt from an implementation-centric spinner into an outcome-oriented,
transparent view of a running scan. Six merged slices; the owning session designed the "Track A" program
(alongside the Track B pipeline ADR below) and logged the #459 session view, so these scan-progress slices
are picked up here. Unbound Feature — no ADO id assigned yet; rebind if the program has one.

- **Outcome-oriented progress line** (#452, slice 1). The live line was implementation-centric — "Reading
  files · 145/250 · Document2.pptx" — naming one worker's current file while the fan-out processes many at
  once, so the filename was never an honest signal. Replaced by a pure, tested view-model
  (`assessmentProgress.js`) that turns the live payload into how much is done, how fast, and how long is
  left — a statement about the **run**, not one worker.
- **Live outcome chips** (#455, slice 2). Adds WHAT is emerging from the run — "97 passed · 23 need review ·
  7 failed · 105 processing" — streamed as files land. No backend change: `get_scan`'s run summary already
  carries certifiable/uncertain/error derived live from `file_records` (the same source `finalize_scan_run`
  aggregates), so the live chips and the final numbers cannot diverge.
- **Expandable "Processing details" table** (#458, slice 3a). A collapsed-by-default per-file table — each
  landed file with its format, result (Passed / Needs review / Failed / Queued) and score, filterable by
  All / Findings / Failed / Completed. Transparency for technical users without forcing everyone to watch a
  scrolling event log; fed entirely by the `file_records` that already stream.
- **Live scope funnel** (#460, slice 3b). Answers, inline and mid-scan, why a 250-file selection assesses
  fewer: "250 discovered · 214 assessable · 25 metadata-only · 11 unsupported · 5 couldn't open". Reuses the
  three-denominator inventory (`estateFunnel.statusRows` over `inventory.by_status`) — the SAME numbers
  EstateCoverage shows on Discover/Overview (#4597), never a second count that could disagree; `blocked`
  (password-protected / couldn't-open) surfaced separately since those files are eligible.
- **Folders as step 1 of the scan wizard** (#461). `ScanScopeWizard` owned the evaluation scope (criteria +
  formats) but never asked WHICH folders — folder choice lived only on the Sources card, so the wizard tuned
  ~50 checks without saying which half of the Drive they applied to. The folder step now goes **first**,
  seeded from the source. The load-bearing decision is the precedence rule: the card holds a folder set per
  **connection**, the wizard chooses one per **run**; the card seeds the wizard (so they agree unless
  diverged), a change applies to THIS run only, and write-back to the card is an explicit tick shown only
  once they differ — closing the 2026-07-30 config-vs-run boundary-mismatch class one level up.
- **"Notify me when complete"** (#463, slice 3c). The scan runs server-side and the banner is non-modal, so
  a user could always work elsewhere; this arms a browser notification that pings the outcome when the scan
  finishes ("145 of 250 assessed · 23 need review"). `scanNotify.js` asks permission once, only on opt-in.
- **Three-step scan wizard with progressive disclosure** (#470). The scan modal was a folder selector, scan
  configurator, WCAG matrix and engine panel all at once; #461 put folders first but *inside* that same dense
  panel, which made it worse. Rebuilt as **three steps — Drive locations → Formats & criteria → Review** —
  folders first because they decide which estate is judged, criteria only how each document in it is judged
  (asking criteria first invites tuning 53 checks over the wrong half of a Drive).
- **Two-column folder browser inline in step 1** (#472). Step 1 embeds the picker — tree on the left, CURRENT
  SCOPE on the right, both visible at once — replacing the "Choose folders…" link into a modal. One
  implementation, two layouts: `FolderPicker` grows `layout="inline"`; the Sources card and Discover keep the
  modal. Adds a folder-scoped, honestly-labelled filter box.
- **Reuse a recent scope, symmetric criteria write-back** (#473). Step 1 offers the boundaries this user has
  **actually run**, derived from `scan_runs.scope` rather than a new saved-scopes store — a run's frozen scope
  is a record of what WAS covered, and only that can be re-offered. Runs with no recorded scope are refused
  (NULL is unknown, and applying unknown applies as *everything*), as are cross-family scopes and the wizard's
  own default; carve-outs carry through by id, labelled, not dropped.
- **Review step reports what this exact scope covered last time** (#474). Deliberately **not** a live pre-scan
  estimate: under ADR 0020 a Discover run *is* the listing, so an estimate is nearly the operation run twice,
  and it would put a second number for the same estate on screen under a different cap — the 2026-07-30 defect
  again. Instead the review step reports a number that was **measured** — what this exact scope covered on its
  last run.
- **Per-stage timing instrumentation (ADR 0037 Step 0)** (#467). The measure-first first step of the Track B
  pipeline design: `stage_timing.py` (pure — `ScanTimings` monotonic-clock accumulator, `merge_rollups` /
  `bottleneck` / `summarize`) times each file's scan by stage (download vs analyse) into its own
  `file_stage_timings` table, surfaced as a per-scan rollup (totals, per-stage average, bottleneck stage). A
  strict **side-channel** — every function is total (malformed input dropped, never raised), so timing can
  never disturb the scoring path it measures. No behaviour change; it exists so the staged speed-up is tuned
  from real numbers, not guesses.
- **`read_timings.py` — read a scan's per-stage rollup** (#478). A stdlib-only CLI over `GET
  /scans/{id}/timings` (signed-in session token) that prints where a scan spent its time — download (I/O) vs
  analyse (CPU + GPU) — bottleneck starred, so the next Track B step (splitting the bottleneck stage into its
  own bounded pool) is chosen from data. Companion to #467; `--json` / `--provider` flags, most-recent scan
  by default.

## Open items (backlog candidates)

- **The docx header/footer parity audit is complete.** All six body-only content checks now read
  the header/footer/note parts: 2.4.4 (#214), 2.1.2/3.3.2/4.1.2 (#229), 1.4.11 (#230), 3.1.2 (#226)
  and 1.4.1 (#227). The never-fail-a-scan contract that backs the registry detectors is pinned
  registry-wide (#224, #228). No open siblings remain from this sweep.

- **~~The v2 redesign is a fork~~ — RESOLVED 2026-08-19.** `frontend-v2/` replaced `frontend/`
  in place; there is now one SPA tree. The duplicate CI job (ci.yml and azure-pipelines.yml both
  carried one) is deleted per ci.yml's own note, the three deploy references that "must agree"
  (Dockerfile, Dockerfile.base-web, redeploy.sh's WEB_HASH) move together, and the generators
  that emitted to both trees emit to one. Netlify's `base = "frontend"` needed no change and now
  serves the same app the Azure image already served — the two deployments had been running
  different SPAs. The four surfaces v2 had dropped (Ontology, UserManagement, WcagCoverage,
  WhatsChanged editors/panels) stay dropped: `v2Simplification.test.js` exists to keep them out,
  capabilities were retained where the UI was not, and `UserManagement` in particular was deleted
  for showing fictional people as the real list of users with access. *(2026-08-19: the cost is now measurable rather than theoretical. Six PRs
  (#328/#343/#357/#360/#365, plus the earlier panel work) each shipped to BOTH trees, so
  `sourceOps.js`, `SourceDrawer.jsx` and both their test files exist twice, byte-identical and
  hand-synced. Duplicating was correct each time — `netlify.toml` still deploys `frontend/`, so
  v2-only would have shipped nothing to the live demo — but ci.yml's own note says "When
  frontend-v2/ replaces frontend/, delete [this job]", and every feature added meanwhile doubles
  the eventual reconciliation. This needs a decision on when the swap happens, not more parallel
  features. Related: `Disposition.jsx` sits in `frontend-v2/src` fully written and mounted nowhere
  since #319 — it reads as live code and is not.)*
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
  `scripts/monitor.py` against `ACP_FQDN`) — `completed/failure` repeatedly, e.g. on `de556b5`. *(2026-08-18:
  investigation concluded.* Not a broken probe or misconfigured `ACP_FQDN`/`ACP_MONITOR_KEY` — every liveness
  and deep check passed; the sole failing check was `production is current` (deploy drift), and it was a **true
  positive**: production genuinely trailed `main` because the gated auto-deploy sat unapproved. #237 fixed one
  false-drift class (a CI-only root file miscounted as image drift) and #238 stopped an approved-late deploy
  shipping a stale sha. The residual is the `production` environment's manual-approval gate stacking deploys —
  ops, not a code bug. Prod was later observed live on a current build (v2026.8.18.2), so deploys are landing;
  confirm the probe run itself is green before closing.*
- **SharePoint discovery under-reports freshly-uploaded estates** (GH #333, found 2026-08-18 in end-to-end
  testing). `_sp_list` enumerates via Graph `search(q='')`, which reads the eventually-consistent search index,
  so a scan soon after a bulk upload sees a fraction of the estate with no "still indexing" signal (39 of ~158
  observed). Fix candidate: a `children`-based recursive crawl (immediately consistent), or an index-lag
  warning. Two more issues filed from the same test: **no way to cancel a running scan, and an in-progress scan
  blocks all new scans** (GH #334), and **very slow local-AI assessment throughput on image-heavy docs** — 1/39
  after ~20 min, worth confirming vision runs on the provisioned T4 GPU vs. CPU (GH #335).
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
  is the auto-fix lane's fixed effort, not a measured estimate). *(Both since closed — the measured
  estimate by `reviewerTime.js`, the rename across all five user-visible surfaces by the entry below,
  and item 1's ProgressRail dropped by the entry after it — so **R4 is closed**.)* **R5** closed — Monitor tab reads the
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
  #290 (folder-scan parity in `_search_folder`, `DRIVE_FIELDS` metadata enrichment), ~~the funnel's
  human-review/published stages still 'pending' (#301)~~ *(RESOLVED — #327 wired both stages, they now
  derive from real progress)*, and the multimedia-captioning LOE (#280: ~10–14
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
- **2026-08-18 (bind)** — Created ADO Feature **#4618** "Discover & Assess lifecycle rules" under Epic
  #3664 (Feature, `AI-Foundry\MovaIO-Build`, Iteration 10, Active; description carries the eight PR
  Tasks + the deferred C4), and bound it to the heading above. No new commits documented.
- **2026-08-18 (C4)** — Documented C4, the deferred location/owner/department scoping, as four Tasks under
  Feature **#4618**: the scope resolver + rule store (#326), per-file scope at the scoring gate (#330), the
  CRUD API + scope-aware eligibility (#329), and the editor UI (#331) — which completes **AC-09**. Also
  folded in three other sessions' commits that landed in this window: #327 (funnel Published/Human-review
  stages wired — resolves the Open item that flagged them) under Estate coverage, and #322 (shard-by-time
  CI balance) under Test corpus and CI. **#328** (a "source operations panel — Overview/Scope/Rules/
  Activity" UI reorg by another session) is covered by this marker but only lightly characterised from its
  subject — it touches the same scope surfaces as C4d and may warrant a reconciliation pass; left for its
  author to bind. Excluded as non-feature: the two delivery-log commits (#323, #324). Sync marker advanced
  from `27827405` to `4d176d36`.
- **2026-08-18 (reconcile + batch)** — Resolved the #328/C4d overlap flagged last sync: #328 and C4d are
  distinct systems (source-drawer lifecycle/discovery vs per-file WCAG scoping), so #338 names them apart
  rather than merging them — added under Feature #4618. Folded in three more commits that landed since the
  last mark: #318 (drops the duplicate `file_tags` RESET entry from the #312/#313 collision — under #4618,
  closes that cleanup), and under Estate coverage #332 (paginated per-file estate export + CSV — delivers
  the #303 follow-up, whose note is updated) and #325 (local source recursive walk with filesystem
  metadata). Excluded as non-feature: the C4 delivery-log commit (#336). Sync marker advanced from
  `4d176d36` to `fad0dfbe`.
- **2026-08-18 (settings + SharePoint validation)** — Back-filled #319 (Platform settings scoped to
  Owners + Users, hide-not-delete of the six other admin panels, equal-weight Microsoft/Google onboarding
  on the Users tab) under v2 frontend redesign. #319 is an ancestor of the current marker `fad0dfbe`, i.e.
  a covered-but-unlogged commit that earlier sweeps documented their own work over — this is a back-fill.
  Recorded an end-to-end SharePoint discovery validation on the deployed app under SharePoint as a document
  source (no commit — testing), and filed its three findings as GitHub issues, added to Open items: #333
  (`search(q='')` index-lag under-reporting), #334 (no scan-cancel / blocks new scans), #335 (slow local-AI
  assessment throughput). Updated the production-probe Open item in place with this session's investigation
  outcome (a true-positive deploy-drift, not a broken probe; #237/#238 fixed two causes; residual is the
  manual-approval gate — ops). #237/#238 confirmed already logged under Continuous deployment; not duplicated.
  **Sync marker deliberately NOT advanced** (left at `fad0dfbe`): the sole new feature commit in the delta,
  #337 (SharePoint three-denominator estate summary), belongs to another session's estate-coverage sweep and
  is left for it to characterise — advancing the marker would swallow it. #339 is a delivery-log commit.
- **2026-08-18 (#337 review follow-ups)** — Added #345 and #346 under Estate coverage — my review of another
  session's #337 (SharePoint three-denominator summary): #345 fixes the blank drill-down samples (triage
  metadata parity with Drive), #346 covers the multi-library truncation branch. #337 itself is still left for
  its author's sweep (per the entry above), so these are recorded as follow-ups referencing it, not a
  re-characterisation of #337. **Marker still NOT advanced** (`fad0dfbe`): the range also holds undocumented
  feature work from other sessions — #340 (rejected-fix lane W2/W8), #341 (per-scan scope chip R6), #343
  (inventory-grain new/changed/removed + Discover tracing), #344 (report scope-of-assertion funnel) — left
  for their own sessions to characterise, the same way #337 is. #342 is a delivery-log commit.

- **2026-08-19 (source operations panel — author sweep)** — Characterised my own six PRs, which two earlier
  sweeps deliberately left for this session: #328 was "covered by this marker but only lightly characterised
  from its subject … left for its author to bind", and #343 was named among the commits "left for their own
  sessions to characterise". Added five bullets under Feature **#4618** (#328 source operations panel, #343
  inventory-grain diff *and* its separate Discover-tracing half, #357 rule match counts + review queues,
  #360 recording-only approval queue, #365 lifecycle audit trail) and one under **#4614** (#352 deployment
  preflight — ops verification, not lifecycle, so it does not belong under #4618). The #338 reconciliation
  bullet stands unchanged: it correctly separates the drawer's lifecycle axis from C4d's WCAG axis, and
  nothing here re-litigates that.

  Worth recording as a pattern rather than six unrelated fixes: **every one of these turned out to be a
  boundary defect**, and in each the obvious implementation produced a correct number that said something
  false in its context — `get_scan_diff` answering a Discover question from assessed data, `discover_span`
  existing with no caller on the discover path, `preview` counting the whole estate under a per-source
  heading, `disposition_audit` having no source column at all, and `list_scans` hiding unassessed runs from
  the baseline lookup. None failed loudly; most were caught only by checking the data source before building
  on it, and two only because a test asserted a precondition that had been assumed.

  **Sync marker deliberately NOT advanced** (left at `fad0dfbe`), same reasoning as the two entries above:
  the range still holds undocumented feature work from other sessions — #347 (monitor retry/dead-letter W7),
  #350 (manual-attestation lane W4+W5), #351 (remediate contextual preview), #354 (per-document progress
  bar), #356 (OpenAI + Anthropic vision adapters), #359/#361/#364 (remediate transform strip, sticky
  workflow footer, adaptive preview modes), #362/#363 (assess coverage-gap warnings and scorecard) — and
  advancing over them would swallow work their own sessions should characterise. Excluded as non-feature:
  the delivery-log commit #349, and this entry's own.

  Updated the **"v2 redesign is a fork"** Open item in place rather than raising a second one: this session
  put six PRs into both trees, so the duplication it warns about is now measurable — `sourceOps.js`,
  `SourceDrawer.jsx` and both their test files exist twice, byte-identical and hand-synced.
- **2026-08-18 (copilot + observability)** — Documented this session's six PRs, none previously in the log.
  The review-card copilot end to end — #367 (palette + escalation path + honest empty state), #378 (backend
  forwarding the escalation path + a non-admin `cloud_enabled` signal), #382 (the card reading those real
  fields, retiring the ledger/zone proxy) — added as three Tasks under **#4598 (AI Work Inbox)**. The
  Langfuse observability catch-up — #368 (G1–G4: generations with model/tokens/cost, nested under the file
  trace, remediation counts), #372 (N1 cloud-vision token usage), #371 (N2 disposition-queue tracing) — added
  as a new **Observability — AI tracing and cost** Feature (unbound; no ADO id known). #356 (vision adapters)
  and #340/#341/#347/#350 are already logged by their own sessions and left untouched. **Sync marker
  deliberately NOT advanced** (still `fad0dfbe`), same convention as the three prior entries: the range holds
  undocumented feature work other sessions should characterise. Context, not edited here: #385 retired the
  `frontend/` fork, which resolves the standing "v2 redesign is a fork" Open item — left for that session to
  close.
- **2026-08-19 (Remediate single decision surface + Deva Assess/Discover lifecycle)** — Documented my
  session's nine PRs, none previously in the log. To **Remediate review queue (#4598)**: #366
  (workflow-status top tabs from real pipeline state), #370 (footer lights the live workflow step), and
  #389/#394 (retired the file-level "Documents to remediate" table and the bulk "Remediation plan" band —
  the inbox is now the single decision surface). To **Discover & Assess lifecycle rules (#4618)**: #383
  (create archival/deletion rules in Discover — Deva #3), #384 (the default scan path evaluates them, not
  only the fanout path — Deva #4), and #375/#379/#381 (Assess ignores flagged files as a visible,
  controllable filter, with the eligibility count and a scope-funnel stage — Deva #6). Deva's already-shipped
  Assess filters (#5 document-type, #7 WCAG-code) noted in place, not re-added. **Sync marker deliberately
  NOT advanced** (same convention as the four prior entries): the SMB source work (#388–#397) and other
  commits in the range remain for their sessions to characterise.
- **2026-08-19 (Langfuse trace enrichment)** — Added #403 and #406 as two Tasks under Observability — AI
  tracing and cost (Langfuse). #403 turns the empty per-file traces ("no input or output") into real
  input (document + format) and output (score / conformant / failing WCAG criteria); #406 extends the output
  with the full per-check breakdown, a PII flag (type categories, never values), and remediation status.
  Both stay inside the PHI privacy guard, with the no-free-text / redaction tests kept green. **Sync marker
  still NOT advanced** (`fad0dfbe`, same convention): the 68-commit delta remains dominated by other
  sessions' undocumented feature work (SMB sources, remediation/certify/monitor lanes, coverage scorecard,
  etc.), left for their own sessions.
- **2026-08-19 (R4 workspace, coverage, scope, GPU)** — Added ten of the day's merged PRs as Tasks. To
  **Remediate review queue (#4598)**: #404/#408/#412/#415 (the R4 workspace rebuilt as a two-column
  master/detail queue with specific decision actions and an editable "Save edited fix" draft), #416
  (preview zoom + grounded fix callouts) and #417 (per-file assignee backend for "Assigned to me"). To
  **Estate coverage (#4597)**: #407 (finding-level remediation-eligible denominator), #413 (the funnel on
  the Discover tab from a shared helper) and #411 (fixed the `inventory_out` regression that crashed every
  local scan). To **Operator scan scope (#4601)**: #410 (per-document selection carried through to the
  certification facts). To **Continuous deployment (#4614)**: #405 and #414 (the vision lane moved off
  RunPod onto an in-tenant Azure GPU, with the SKU resolved from the region). **In flight, not yet logged
  as done:** #418 splits the folded preview back into a dedicated **third pane** (the guided-work-queue
  mockup) — it supersedes #408's two-column fold; a later sync records it once merged. **Sync marker
  deliberately NOT advanced** (same convention as the prior entries): the surrounding delta stays for the
  other sessions to characterise.
- **2026-08-19 (R4 PR5 — Not applicable)** — Added #422 to **Remediate review queue (#4598)**: the
  first-class out-of-scope decision PR4 deferred, reusing the per-finding `resolution` mechanism (not a new
  HITL status, which would have stranded certification) and lifting the v1 `not_applicable` folding into a
  real reported bucket that LEAVES the coverage denominator — so the reported % rises, matching the WCAG
  matrix's N/A treatment. Backend + frontend, not RULE_PATHS (all four backend checks green). For the
  record: **#418 has since merged** (`42e125e4`, "three-pane guided work queue — mockup A"), which
  SUPERSEDED #408's two-column fold with a dedicated three-pane layout — the in-flight item the prior entry
  flagged, now landed. PR5's N/A decision is layout-independent and rides on either. **Sync marker
  deliberately NOT advanced** (same convention).
- **2026-08-19 (Remediate layout controls)** — Added #427 to **Remediate review queue (#4598)**: an
  Outlook-style Split / Stacked / Focus toggle and pointer-and-keyboard resizable dividers over the #418
  three-pane workspace, with the layout + pane sizes persisted in `localStorage`. Named to avoid colliding
  with the preview's own Before/After/Side-by-side (document-diff) control. Frontend, not RULE_PATHS
  (frontend suite green at 2055). **Sync marker deliberately NOT advanced** (same convention).
- **2026-08-19 (Remediation redesign from operator feedback + metadata-only Discover)** — A detailed operator
  critique of the Remediate tab drove five PRs, added to **Remediate review queue (#4598)**: #430 (default
  workspace → Stacked), #434 (the 5-stage taxonomy — Needs review / Manual fixes / Awaiting validation /
  Blocked / Completed — fixing the auto-fix double-count and the reachability dead-end), #433 (decision-first
  right pane + adaptive, grounded evidence, and the "structure/metadata" copy-bug fix classified by criterion
  nature), #437 (issue-led scannable rows with a WCAG pill and quiet lane state), and #435 (the hero "N need
  review" derived from the same Needs-review population so the two counts can't diverge). Cross-session
  coordinated with the state-model owner throughout, preserving the ADR 0016 honesty invariants (Awaiting
  validation ≠ Completed; not_applicable terminal + out of denominator; no fabricated geometry/ratios/pager).
  Separately, to **Discover & Assess lifecycle rules (#4618)**: #436 made discovery metadata-only by default
  (download deferred to Assess) and aligned the frontend `pii` default to off. **Sync marker deliberately NOT
  advanced** (same convention as the prior entries).
- **2026-08-19 (Bell count alignment)** — Added #442 to **Remediate review queue (#4598)**: aligned the
  top-nav notification bell to the same `matchesWorkflow('needs-review')` count as the hero (#435) and the
  tab (#434), so all three review-count surfaces show one number, with a source guard against regressing to
  `queue.length`. Cross-session hand-off from the state-model owner's session (they owned the `onHitlCount`
  seam but were blocked; ownership flipped with their confirmation). **Sync marker deliberately NOT advanced**
  (same convention).
- **2026-08-19 (Langfuse v3 upgrade)** — Added one Task under Observability — AI tracing and cost (Langfuse):
  the v2→v3 migration that moved the trace store to ClickHouse on a dedicated Azure VM so the enriched
  (#403/#406) Session view stops hanging on large scans, cut over host-only, and deleted the old v2 app.
  #447 (`deploy/langfuse-v3/`) captures the runbook + compose so the hand-provisioned move is reproducible.
  This is ops + one docs-only PR, not a RULE_PATHS change. **Sync marker still NOT advanced** (`fad0dfbe`,
  same convention as the prior entries): the large delta since it remains other sessions' undocumented
  feature work, left for them to characterise.
- **2026-08-19 (Architecture docs refresh)** — Added the architecture-deck + long-form refresh (#432, #438,
  #439, #444) to **Documentation**: the AI-lane / Observability / Sources / two-chain-CD / status-model
  corrections and the new Scan→Assess→Remediate vision/GPU-routing slides (with the real T4 sizing). NOTE:
  the deck framed Langfuse v3/ClickHouse as the *committed migration*, but the actual v3 cutover then shipped
  (see the Langfuse v3 upgrade entry above, #449/#447) — so the deck's Observability slide needs a follow-up
  to say v3 is **live**. The Remediate workspace/layout/taxonomy/count PRs (#418/#427/#430/#434/#435/#442)
  were already logged under #4598 by the state-model owner's session, so nothing was added there. Docs-only,
  not RULE_PATHS. **Sync marker deliberately NOT advanced** (same convention).
- **2026-08-19 (in-app trace panel)** — Added #454 as one Task under Observability — AI tracing and cost
  (Langfuse): viewing a document's trace INSIDE AccessOps with no Langfuse login. Recorded the verification
  that drove the design — Langfuse's own public trace page hangs for a logged-out visitor on our self-hosted
  v3 and can't be iframed, so the durable path is a server-side proxy (`lf.fetch_trace` + a `/trace/file/
  {file}/data` route) rendered by a `TracePanel` drawer, not a public deep-link. Backend + frontend, CI green
  on `main`; not a RULE_PATHS change. **Sync marker still NOT advanced** (`fad0dfbe`, same convention as the
  prior entries): the large delta since it remains other sessions' undocumented feature work.
- **2026-08-19 (in-app session view)** — Added #459 as one Task under Observability — AI tracing and cost
  (Langfuse): the whole-scan session view #454 deferred (`lf.fetch_session` + `/trace/session/data` +
  `SessionPanel`, with per-file drill-in), plus the #454 result-shape fix the live data exposed (failing
  criteria is a dict, PII is `{flagged, types:[…]}` — the panel and its fixtures had the wrong shape).
  Backend + frontend, CI green on `main`; not a RULE_PATHS change. **Sync marker still NOT advanced**
  (`fad0dfbe`, same convention as the prior entries): the large delta since it remains other sessions'
  undocumented feature work.
- **2026-08-19 (session view browser verification)** — Recorded a no-commit testing note under the #459
  Task: the session view was driven in the browser (SIM mode) against the merged `origin/main` and confirmed
  at the DOM — SessionPanel rollup/rows/not-assessed, in-app chip, drill-in to the file TracePanel, and the
  #454 shape fix rendering (failing-criteria chips, PII categories), no console errors. Verified from a
  throwaway `origin/main` worktree because `preview_start` serves the stale shared checkout. Testing only —
  **sync marker unchanged** (`fad0dfbe`, same convention).
- **2026-08-19 (scan scope, sources, auth, GPU preflight + deck-v3-live follow-up)** — Added the day's
  remaining non-Track-A merges. To **Operator scan scope (#4601)**: the per-user scan-scope override end to
  end — #424 (widen-only resolution wiring), #429 (`/settings/mine` route), #445 (the Settings-UI editor,
  ADR 0035) — and folder-level source scoping, #441 (choose folders per source card) + #451 (child
  exclusions + actually applying the saved scope). To **Discover & Assess lifecycle rules (#4618)**: #443
  (default Incremental **off** so the baseline scan skips nothing). To **Multi-tenancy and the control plane
  (#4608)**: #453 (a Google/Microsoft account chooser at sign-in). To **Continuous deployment (#4614)**:
  #450 (the GPU-vision preflight now recognises the ollama-on-GPU path and probes the model — closing the
  #302 blind spot). To **Documentation**: #457, the deck Observability-slide follow-up the architecture-docs
  entry flagged (v3 is now stated as **live** on the Azure VM). **Deliberately left for the owning session:**
  the Track-A scan-progress/transparency stream (#452, #455, #458, #460, #461, #463) — a cohesive sequence of
  slices being logged by that session. **Sync marker deliberately NOT advanced** (same convention as the
  prior entries).
- **2026-08-19 (Track A scan-run experience + ADR 0037)** — Picked up the Track-A scan-progress stream the
  prior entry had deferred: the owning session logged the #459 session view (under Observability) but not the
  six scan-progress slices, so with the log now current elsewhere they are added here as a new **Feature —
  Scan-run experience (Track A)** (unbound, no ADO id yet): #452 (outcome-oriented progress line), #455 (live
  outcome chips), #458 (Processing-details table), #460 (live scope funnel, reusing #4597's three denominators),
  #461 (folders as step 1 of the scan wizard, with the connection-vs-run precedence rule) and #463 ("notify me
  when complete"). To **Documentation**: #464 — ADR 0037, the measure-first staged/bounded assessment-pipeline
  design (Track B; design only, no runtime change). **Sync marker deliberately NOT advanced** (same convention
  as the prior entries).
- **2026-08-19 (scan wizard + timing instrumentation + arch-doc reconcile)** — To **Scan-run experience
  (Track A)**: the wizard build‑out on top of #461 — #470 (three‑step progressive‑disclosure wizard), #472
  (inline two‑column folder browser), #473 (reuse a recent run's frozen scope, symmetric write‑back), #474
  (review step reports the *measured* last‑run coverage, not a fabricated estimate) — plus #467, ADR 0037
  **Step 0** per‑stage timing instrumentation (a total side‑channel that measures download‑vs‑analyse without
  touching the scoring path). To **Documentation**: #475, the long‑form `acp-architecture.md` reconcile
  (Langfuse v3 live, per‑user scope end‑to‑end, GPU T4, ADR 0037 as the concurrency fix). **Deliberately left
  to their owning streams:** #419 (SMB walk/read logic, ADR 0036) belongs to the multi‑session SMB source
  program (#388–#397) this log already defers to its owner; #476 is a trivial `.gitignore` chore. **Sync
  marker deliberately NOT advanced** (same convention as the prior entries).
- **2026-08-19 (remediation-honesty fix + timing reader)** — To **Remediate review queue (#4598)**: #479 —
  stopped the Review queue claiming "every fix was applied automatically" over files that could not be read
  (skipped was being reported as done); the caveat is now appended to whatever the queue renders, and the
  count is gated on files opened-and-failed, not every non-certifiable file. To **Scan-run experience
  (Track A)**: #478 — `read_timings.py`, the stdlib CLI that reads #467's per-stage rollup so the next Track B
  step is chosen from data. **Sync marker deliberately NOT advanced** (same convention as the prior entries).
- **2026-08-19 (SharePoint-fetch root cause + Remediate: honesty, assignee, a11y, adaptive evidence)** — One
  root-cause chain plus three Remediate features. To **SharePoint as a document source (#4600)**: #481 — the
  driveId was dropped in `norm`, so SharePoint files routed to the Drive download branch and every one recorded
  `status='error'`; they were never fetched, not unreadable. To **Remediate review queue (#4598)**: #483 (the
  #479 follow-up — the drawer now shows the *recorded* per-file reason instead of guessing "unreadable", the
  copy that had been shown over #481's 22 never-fetched SP docs), #482 ("Assigned to me" filter + assign,
  wiring #417's backend), #484 (keyboard + screen-reader operability for the queue — roving tabindex + auto-
  advance announcements), and #485 (adaptive per-finding evidence — real-data-only alt-text + metadata
  renderers, structural findings deferred to a backend data effort; cross-session coordinated with this
  session on scope and the honesty tier). **Sync marker deliberately NOT advanced** (same convention as the
  prior entries).
- **2026-08-19 (SMB readiness on /readyz)** — To **Continuous deployment (#4614)**: #487 — wired the existing
  `describe_smb_readiness()` into `GET /readyz` as an informational `sources.smb` block (defended so a source
  probe can't 500 it; not folded into `degraded`, since a Drive/SharePoint-only deployment legitimately has no
  SMB config). A self-contained health/readiness surface — distinct from the SMB source discovery/transport
  program (#388–#397/#419) still left to its owning session. **Sync marker deliberately NOT advanced** (same
  convention as the prior entries).
