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


- **Delta sync reached interactive scans, not just the scheduled sweep** (#951, #961, #963, #978,
  #979, #981, #984, #994, #1007). SharePoint delta sync was added to the scheduled sweep (#961) and
  then to interactive scans (#981), with Drive following the same path (#978, #951); reconstructed
  listings feed the real scan pipeline rather than a parallel one (#979). Two things had to be true
  first — SharePoint checksum support, which is what unlocks ADR 0011 reuse (#963), and Content Type
  carried through a delta-sync reconstruction (#1007, TODO P1e). Interactive delta sync was decoupled
  from the incremental flag (#984) so a caller could not silently get a full re-list, and Drive
  reconstruction was verified against the same Google account (#994). The failure this prevents: a
  30k-file estate re-listed from scratch on every scan is the difference between a scan that finishes
  and one the customer cancels.
- **Source freshness became a vocabulary rather than a timestamp** (#945, #955, #973). Discover
  surfaces source-freshness (#945) with the fuller PRD Phase 3 sync-state vocabulary (#973), and
  worker-heartbeat age as a third freshness signal (#955) — so "is this list current?" has an answer
  that tells a stale source apart from a dead worker.


### 2026-09-04 → 2026-09-07

- **Multi-site SharePoint discovery finished, Phases 1 → 4b** (#1303, #1313, #1323, #1326, #1332,
  #1337, #1346, #1357). Site enumeration, SharePoint-native metadata and freshness, per-site
  checkpoints with resumable scans, concurrent library walks with site coverage on the map, and
  Graph throttling with an exception report. Freshness is read from SharePoint itself rather than
  re-derived, so a scan no longer re-downloads a library that has not changed.
- **A thirty-site scale proof, and the per-document Graph call it exposed** (#1355). The proof was
  run rather than asserted; it found a per-document Graph round-trip that only shows up at estate
  width. #1424 then wrote down what actually counts as one of the thirty locations, so the number
  means the same thing to the customer and to the code.
- **Release into SharePoint made durable against the five ways it was failing** (#1447, #1468,
  #1475, #1496, #1498, #1500, #1504). Name races now fail atomically instead of half-writing;
  release folders are recovered after a crash; duplicate filenames are preserved rather than
  silently overwritten; collisions beyond page one of the listing are caught (page one was the only
  place the old check looked); incremental totals are reconciled; and the Microsoft access token is
  refreshed through long releases, which is the failure a large publish hits and a small one never does.
- **Assessments scoped by content type** (#1398), **SharePoint scope shown across workflow cards**
  (#1351) and **guarded across workflow stages** (#1385), so a SharePoint-sourced run cannot present
  itself as a Drive one.
- **Remediation reads the source cache under the key Assess wrote** (#1359) and remediates from that
  cache one batch at a time (#1341) — the mismatch meant SharePoint remediation was refetching.
- **A refusal now says whose problem it is** (#1352): a Graph 403 reports whether the tenant, the
  scope, or the item is at fault, and what the tenant admin will see when asked.
- **The production canary became a verifiable evidence gate** (#1491) and release canaries **fail
  closed when incomplete** (#1506) — an unfinished canary used to read as a pass.
- Corrected stale SharePoint parity claims in the docs (#1395) and made the folder-rule gap document
  state what is true rather than what was planned (#1358). Four `importlib.reload` calls in the
  SharePoint tests were breaking two tests in an unrelated file (#1431).


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


### 2026-09-04 → 2026-09-07

- **Scheduled scans became operable** (#1660, #1664, #1684). User-timezone schedules (with the
  timezone shown beside the account name, #1650), operational controls for pausing and forcing a run,
  and reliability polish. A schedule expressed in server time is a schedule the customer reads wrong.
- **Narrow scans no longer masquerade as full sweeps** (#1520) and **no longer lock the workspace**
  (#1524); the selected Discovery scope stays visible while the scan runs (#1577).
- **Replacing a Discovery now requires confirmation and offers continuity** (#1493, #1495), and the
  exact recent workflow is offered before a rescan (#1505) — three separate paths that used to
  discard a completed estate scan on a single click.
- Scan history replays chronologically (#1598) and names the workflow revision behind each run (#1507).


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


- **Discover's queued state stopped contradicting itself** (#993, #1027, #1030, #1031, #1043). Three
  contradicting queued-state signals were fixed and clarified (#1027) and the UI consolidated into a
  single card (#1031); an unclaimed scan job could hijack the UI forever (#1030); the missing
  "previous inventory unaffected" line was restored and a scan ID added to the failure banner (#1043);
  and Discover's indefinite "Loading your inventory…" plus a worker-capacity false alarm were fixed
  (#993).
- **Smaller UI corrections** (#943, #944, #946, #948, #949, #956, #1130, #1188, #1204). The completion
  card's inventory-delta question redirected to SourceDrawer (#943) and its key stats bulletized
  (#946); the top-nav scannable-document count labelled and Time-travel's epoch date fixed (#944);
  cancelled/interrupted scans labelled in the Recent scans table rather than shown as 0 (#948); the
  status word itself shown in Docs/Certifiable instead of a separate badge (#949); a browser
  notification on scan **failure**, not just completion (#956); a WCAG-compliant palette toggle in the
  header (#1204); lifecycle results and folder metadata polished for Deva (#1130); and FastPass
  failures fixed in the production shell (#1188).


### 2026-09-04 → 2026-09-07

- **The People and Roles screens were unusable in four distinct ways, all now fixed** (#1407, #1444,
  #1457, #1464, #1535, #1571, #1579). The screen listed people it then refused to give a role to; the
  role dropdown did nothing because its confirmation rendered off-screen; the row holding role
  assignment wrapped so the control was unreachable; the dropdown closed under the cursor because
  App's polling re-committed the select; a hidden Settings tab was not hidden; and the confirmation
  toast covered — and swallowed the clicks of — the rows beneath it. Each was a control that appeared
  to work and did nothing, which is worse than a control that is visibly broken.
- **Application header and account controls simplified** (#1296); provider links styled as source
  actions (#1402); duplicate source-drawer actions removed (#1426); connected content sources open in
  their provider (#1314). The connector drawer had eighteen labels for classes nothing writes (#1418).
- **The WCAG token migration was finished and the allowlist emptied** (#1483, #1476, #1286, #1320).
  Seven undeclared custom properties, then an eighth, were fixed and the allowlist that was hiding
  them removed; three `--text` uses were pointed at the declared `--ink`; icon-button, upload-step,
  assess-pipeline, segment-bar and verify-track contrast failures were closed. The product asserts
  contrast conformance for customers, so its own shell failing it is a credibility defect.
- **Machine values render identically wherever they appear** (#1716). Sixteen components each reached
  for their own monospace/tabular-figure styling for counts, ids and timings, so the same number
  looked different between the Remediate inbox, Monitor and the run drawers; one `styles.css` class
  now owns it and `typographyConsistency.test.js` fails a component that re-invents it. Inconsistent
  number rendering is what makes two surfaces showing the same figure read as two figures.




## Feature: Dependency security · #4603

- **Upgraded pdfjs-dist to 6.2.108, closing arbitrary JavaScript execution on opening a
  malicious PDF** (#194, GHSA-hq66-cqwq-w95j, HIGH). Also dompurify ≤3.4.12, where
  `CUSTOM_ELEMENT_HANDLING` bypasses `afterSanitizeElements` and `IN_PLACE` hook removal leaves
  a detached subtree executable (GHSA-c2j3-45gr-mqc4, GHSA-55q2-fjhq-7xh7). Found by
  `npm audit --omit=dev` on both SPAs — **`--omit=dev` is the part that matters**, because these
  are not build tooling: they ship to the browser. A platform whose entire purpose is ingesting
  untrusted documents cannot carry a parse-a-PDF-and-run-JS bug.

- **vite upgraded to clear moderate and high CVEs** (#672, P3.5).


### 2026-09-04 → 2026-09-07

- Fail fast when shared scan credentials cannot be stored (#1564), and Key Vault write-through that
  accepts a key value and stores none locally (ADR 0050, #1353). Telemetry endpoints are treated as
  credentials rather than as collectors (#1438) — they carry account-identifying data.


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


- **Vision providers gained a governed activation path, and OCR stopped lying about what it read**
  (#1033, #1140, #1157, #1195). The OpenAI and Anthropic vision providers completed their governed
  activation path (#1157). An image OCR could not read is no longer reported as an image with no text
  in it (#1195) — the silent degradation that makes a clean report untrustworthy — and image OCR work
  is now bounded and reused rather than repeated per finding (#1140). House style reaches 1.1.1 alt
  drafts, the one criterion it could not (#1033).


### 2026-09-04 → 2026-09-07

- **Four vision providers behind one governed activation path** (#1335 Gemini, #1342 Bedrock, #1414 +
  #1427 Hugging Face endpoint health with nearest-rank p95 and window exclusion, #1545 Claude
  `claude-haiku-4-5` promoted to primary text+vision provider). Optional vision now **fails fast when
  unavailable** (#1637) instead of degrading silently into a run that produces nothing usable.
- **Assessment-time cloud escalation for LOW-confidence findings** (#1283), governed (#1460),
  track-managed (#1455), restored under AI governance after a regression (#1458) and surfaced across
  live assessment and operations (#1463). A second opinion that is invisible cannot be audited.
- **HITL image review got a working assistant** (#1301 "Help me" copilot, ADR 0019 Phase 2; #1297 a
  context-aware guidance sentence replacing a terse reason; #1299 a zoom label that says which image
  "THIS" refers to; #1292/#1294 assess-time pre-draft wired through `describe_image_structured`).
- **Reviewer edit-rate feeds back as an automation maturity signal** (ADR 0019 §8.5, #1305), and a
  nightly Review Memory derivation job was added (ADR 0021, #1372). Constrained decoding was measured
  and reported honestly: it fixes the output format and moves no quality gate (#1333).


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

- **A real browser suite over the discover → assess pipeline** (#857, #859, #876, #832). Playwright driving
  the actual pipeline end to end (#857), with vite bound to `127.0.0.1` so the CI readiness probe could
  connect (#859) and an Assess-tab visibility wait replacing a bare click (#876). Comprehensive scale tests
  for the deferred discover pipeline (#832). The suite immediately earned itself: a UI wording change broke
  the `VersionToastBanner` assertion (`69a29c3a`) — caught in CI rather than in staging.
- **Unit coverage where the queue logic now lives** (#718, #714, #710, #703, #861, #838). `scan_batch` item
  analysis, finalize trigger and premature-finalize guard (#718); `rescore_file`, `assess_trace` and
  `_verify_residual_scs` (#714); six lifecycle gaps — contains, null dates, disabled, actor scope, tag dedup,
  delete-excluded (#710) — plus boundary conditions and multi-policy conflict resolution (#703).
  `test_scan_never_started_fix` was **leaking a mocked scanner into the rest of the suite** (#861), and
  `drive_token` cross-replica resolution is now pinned for `scan_discover` (#838).


- **The labelled ground-truth corpus went from 15 to 40 verified pairs, and CI ratchets it** (#1009,
  #1012, #1014, #1016, #1018, #1021). .xlsx started at 4 pairs (#1012) and reached 23 by zip-part
  injection for four more criteria (#1014); .pptx added 9 (#1016, 23 → 32, 52%); .pdf added 8 (#1018,
  32 → 40, 65%). Fixture coverage is reported and **ratcheted so it cannot shrink** (#1009), and the
  corpus invariants are enforced in one place for every corpus (#1021) rather than per-corpus and
  drifting apart.
- **Criterion × format coverage 44 → 54 of 62** (#1020, #1029, #1038, #1042, #1047, #1050). 1.3.3 on
  xlsx/pptx/pdf (#1038, 44 → 47, 76%), 1.4.5 on the same three (#1047, 48 → 51), 3.1.2 (#1050, 51 →
  54) with the corpora given their text lane. Two of these are corrections rather than additions: pdf
  2.4.2 and 3.1.1 were covered after **the earlier claim that they were unreachable turned out to be
  wrong** (#1020), and the .pdf corpus was carrying an *unearned* 2.4.2 control, removed while 1.3.1
  was covered (#1042). #1029 fixed a 3.1.1 the xlsx corpus was already carrying incorrectly. #1047's
  own note is the part worth keeping — it closed the hole that had let the previous pass skip them.
- **Test-suite hygiene — mostly defects the suite was hiding** (#1083, #1093, #1095, #1098, #1105,
  #1114, #1131, #1141, #1176, #1193). The suite was leaking every fixture directory it built (#1083)
  and pruning a **live** session's temp directory on age (#1093). A store test double could never have
  been called by production (#1105); Drive test doubles are now isolated (#1141); two AssessSummary
  test files differed only in case (#1114). Three tests were passing without testing anything: the OCR
  corpus assertions never took the skip their own docstring promised (#1098), one skipped forever on a
  dependency nobody declared (#1176), and a parallelism test proved parallelism **by winning a race**
  (#1193). The pool-exhaustion load test now waits for saturation instead of sleeping (#1131), and the
  job queue is tested on the database it actually runs on (#1095).


- **Two e2e regressions caught by the suite that was just built** (#898, #899, #942). The pipeline spec was
  matched to the "files inventoried" wording (#898) and to #941's completion-card timestamp (#942), and
  shard-4's cross-test module poisoning was stopped **at the source** rather than worked around (#899).


### 2026-09-04 → 2026-09-07

- **Measured whether the detector tests would notice the detector being wrong** (#1503) and tested
  the one PRD 9 guard that nineteen mutations found undefended (#1456). Mutation testing is the only
  check that distinguishes a test suite from a suite of assertions that happen to pass.
- **Checked the docx detectors against an OOXML implementation that is not ours** (#1487) — a
  detector validated only against the writer it was built alongside proves nothing about real files.
- **Three flaky or false-green CI failures fixed** (#1429 two worker-boot tests racing a fixed sleep
  against `import core`; #1594 a backoff test that asserted the dice and so failed at random on other
  people's PRs; #1604 a CI job running a Python nothing ships, plus a gauge calling a busy service idle).
- **A pending CI run is cancelled too, so main's middle commits never shipped** (#1627). Cancel-in-progress
  was cancelling queued runs for commits that then merged unverified — the class of bug where the
  dashboard is green because nothing ran.
- Made the legacy readiness probe work in CI (#1589).


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


- **All 17 remediation lanes proven end to end — 0 → 17 of 17** (#1058, #1067, #1069, #1073, #1074,
  #1076, #1077, #1078). The REMEDIATION-VERIFIED denominator closed on one bar held constant for every
  lane: the original document trips the finding, an approval changes the saved document, **a real
  re-scan verifies it**, unrelated content survives, and a failed write earns no credit. docx 2.4.4
  first (#1058), then 1.1.1 pptx and 3.1.2 docx (#1069), 2.4.4 pptx and 1.1.1 docx (#1073), five more
  (#1074, 6 → 11), the 1.3.3 sensory rewrite across all three Office formats (#1077, 11 → 14), and the
  last three (#1078). The one worth reading is 2.4.6 xlsx: it was written and **deliberately withheld**
  because renaming only the sheet tab left every formula, defined name and chart series referencing a
  sheet that no longer existed (#1076, #1067). Registering it on that evidence would have certified the
  damage; the guarantee is now asserted through the lane rather than through the writer alone.
- **Remediate became an automation-first workspace** (#1144, #1145, #1147, #1203). A two-panel review
  workspace (#1147) with automatic batches and contained review layout (#1144), and predicted Assess
  stragglers scheduled first (#1145) so the long tail stops deciding the run's wall-clock. #1203 fixed
  execution, preview and live progress together.


- **The engine condition attached to the 17-lane milestone** (#1097) — so the "17 of 17" claim carries the
  condition under which it holds rather than standing bare.


### 2026-09-04 → 2026-09-07

- **Archival will no longer move a file out from under someone.** Four independent guards: check
  whether a document can be overwritten before archiving it (#1371), check who is still working on it
  (#1361), treat access as distinct from use — whether anybody has actually opened it (#1369) — and
  archive automatically only where something is *proven* to have replaced it (#1472). Approving an
  archival candidate now actually moves the file (#1374); it previously recorded the decision and did
  nothing.
- **Autoscale remediation within the database connection budget** (#1370) and drain workers on deploy
  while reducing in-flight remediation work (#1366) — remediation could previously exhaust Postgres
  connections and take the API down with it.
- **One server-owned account of a remediation run, instead of five subsystems' counters** (#1376).
  Five components each maintained their own progress arithmetic and disagreed; the run is now counted
  once, server-side, and every surface reads that.
- Remediation exceptions made actionable, with a delivery-only retry that cannot silently re-fix
  (#1474); recovery made bounded and explicit (#1525); finding counts reconciled (#1616); remediation
  batches bound to the approved decisions behind them (#1488).
- **pptx 1.4.5 genuinely clears: the image of text is replaced, not described** (#1715). The old lane
  wrote the OCR transcript into the picture's `descr` — a 1.1.1 improvement that can never satisfy
  1.4.5, which is why #1665 downgraded it to HUMAN. Measured first: `ocr._ooxml_images` reads
  `ppt/media/*` straight out of the zip, so **deleting the `<p:pic>` does not clear the finding** —
  only deleting the media part does, and a test pins that. The new
  `apply_pptx_image_replacement` turns each approved picture into a real text box at the same
  rectangle and drops the media part, and **refuses** (withholding credit) when the image is
  referenced by a layout or master, sits in a group, or has no `<a:xfrm>` of its own. 1.4.9 is
  deliberately left HUMAN — it is AAA, exempts nothing, so its rows can be charts, and replacing a
  chart with its axis labels destroys information. pptx 1.4.5 moves HUMAN → ASSISTED, the write-lane
  count 18 → 19, and a round-trip fixture additionally asserts the replacement introduces no new
  failure.
- **The applier registry is derived from the tests that prove it, not from a hand-written list**
  (#1707). `test_capability_assisted_contract.py` held a frozenset "verified by tracing" — and tracing
  is reading, which is how pptx 1.4.5 sat in that set for months while its verify gate refused every
  approval. Each round-trip fixture now declares `PROVES_LANES`, read by AST, and admitted only if the
  module visibly runs the production seam. Deriving it found the gap the list hid: pptx **2.4.6 had no
  round-trip fixture at all**, and writing one exposed a live hole — `office_structure` counts a
  `ctrTitle` placeholder as a slide title while the writer matched only `type="title"`, so an approved
  title on a Title Slide was silently returned unresolved and never credited. Fixed; the generator now
  reports 18 of 18.
- **The retired pptx `descr` writer is asserted orphaned rather than left looking live** (#1724). A
  complete, fully unit-tested module with no caller reads as shipped code to anyone who greps it — the
  same shape that had ten unmounted components being reported as delivered. Three structural (AST, not
  substring) assertions keep the file for reversibility while proving nothing calls it, and each was
  bite-checked.
- **A fix that breaks another criterion no longer certifies the document** (#1712). #1680 recorded the
  regression and left the policy open; this closes it. Every write-back lane asks only whether *its*
  criterion cleared, so a deck whose approved alt text cleared 1.1.1 and tripped 1.4.3 reached
  `compliant=1`, `score=100`, `status='pass'` and Publish — certified against a criterion it was
  failing. The corrected file is still kept; only the conformance claim is withheld, and a review row
  is raised naming what broke. Three details are load-bearing: only the **credited** path counts (a
  regression inside a discarded write is evidence about the model, not a fact about the file, which
  corrects #1680); the row is keyed `{criterion}/regressed` so `_superseded_items` cannot retract it
  the instant it is written; and the gate **fails closed** on a missing row, because a regression
  nobody can see in the inbox is exactly the one that must not certify on silence. Seven bite checks,
  one of which started green and exposed a faulty test.




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

- **Dead-lettered work stopped disappearing from the arithmetic** (#668, #851, #666). A dead-lettered job now
  leaves its document in the count (#668) and a dead-lettered `scan`/`scan_discover` job marks the scan
  failed (#851) instead of leaving it eternally "running"; the unverified lease is bounded, and a count that
  was always zero was removed (#666).
- **Classification and scoring fixes** (#833, #653, #652, #660, #603, #692). Image and video MIMEs handled in
  `classify_from_metadata` (#833); a minimal-prompt retry for moondream (#653); severity levels recalibrated
  with a unified palette (#652); scope resolution guarded so **one corrupt scope could no longer fail every
  file in the run** (#660); and `annotate()`'s filename guess was defeating the classification-honesty check
  (#603). A Continue-to-Assess button now appears when only non-assessable files were found (#692) rather
  than a dead end.

- **Fail closed when an analysis engine is missing** (#952, #967, #991, #992, #995, #998, #1005, #1060,
  #1066, #1070). A missing analysis engine now fails closed **everywhere it could silently pass**
  (#1005). The assessment scope is re-adopted after a save, not only at boot (#991); the monolithic
  scan path populates `scan_inventory` and guards against an inventory-less baseline (#995).
  `DispositionRules` stopped writing state from a request that outlived its mount (#1070); Assess
  stopped saying "nothing is processing them" about a job a worker was running (#1060); the Assess
  topology/health split was finished and worker provisioning taken off the user's screen (#1066).
  Orphan-component drift surfaced by an ADR audit was fixed and the list enforced (#992), the Phase 3
  sync review's remaining low-severity findings cleaned up (#998), a weekend review pass found four
  more (#952), and a flake #964's pause checkpoint had introduced was fixed (#967).


### 2026-09-04 → 2026-09-07

- Live assessment updates made adaptive and resilient (#1479); the assess tier pinned warm at 5-5 as
  production actually runs it (#1405); the assessment card kept visible across tabs and on its own tab
  (#1437, #1446); the rolling heartbeat bars restored (#1625) and the sparkline moved into live status
  (#1621).
- **"12 of 70 documents processed" said nothing had been processed** (#1561) — a completeness figure
  that read as zero progress while two thirds of the estate was done. Live processed-document
  completeness is now shown during remediation (#1511).


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
- **Multiple Platform Admins, not just the single owner** (#534). The admin surfaces (scope editor,
  platform Settings, access management) were gated to exactly one identity — `ACP_OWNER_EMAIL` — so a
  second person could sign in and scan but never see the same admin UI. Added `ACP_ADMIN_EMAILS`: a set of
  additional admins with the same rights. `core.is_admin` is the single source of truth both the SPA flag
  (`is_scope_owner`, now delegating to it) and the API gate (`_require_admin`) read, so UI and server can't
  disagree; `email_allowed` admits admins unconditionally; `OWNER_EMAIL` stays the anti-lockout owner.
  **No-op until configured** (empty `ACP_ADMIN_EMAILS` = today's behaviour). 9 tests. Not RULE_PATHS.
- **In-app Platform Admin management — owner promotes from Settings → Users** (#535, on #534). Requested so
  a teammate can be granted the same admin UI without an Azure/env change or redeploy. Three tiers, each
  rendered distinctly and none editable into an unsafe state: the immutable **owner** (`ACP_OWNER_EMAIL`),
  **permanent env admins** (`ACP_ADMIN_EMAILS`, "set at deploy", no toggle), and the **owner-managed set**
  (store `admin_emails`, promote/demote here). `store.get_admins`/`set_admins` mirror the allowlist;
  `core.is_admin` now unions owner ∪ env ∪ store; `core.is_owner` is the strict root-of-trust check;
  `GET/PUT /admin/admins` with the PUT **owner-only** (`_require_owner` — an admin can't grant admin nor
  remove the owner, and the owner/env grants are kept out of the managed set); `/me` + `/config` emit
  `is_owner` so the SPA shows the promote/demote controls to the owner only. Settings → Users gained admin
  badges + an owner-only Make/Remove-admin toggle. 7 backend + 3 frontend tests. Not RULE_PATHS.

- **The route allowlist was fail-open; it is now a fail-closed gate** (#630, #632). #630 found **five route
  groups shipped unauthenticated, one of them a write endpoint** — the allowlist model meant any route added
  without an explicit entry defaulted to public. #632 inverts it: unlisted routes are denied. This is the
  highest-severity finding in the window.
- **Owner scoping and isolation** (#872, #796, #690, #613). `POST /scans/{sid}/remediate` scoped to the
  requesting owner (#872); owner-email isolation tests plus a fan-out load harness (#796, R11 — load test
  PASS 2026-08-25, #817); SharePoint silent token refresh with mid-scan logout cleanup (#690); and a second,
  separate production SharePoint tenant connected as a scan source (#613).
- **Recorded as reverted — the `/internal/admin/sql` endpoint** (#873 → #874, #875 → #878). A protected
  endpoint for programmatic DB access was merged (#873) and reverted the same day (#874), re-landed using
  `cursor()` instead of `connect()` (#875), and reverted again (#878). **Net effect on `main`: no admin SQL
  endpoint exists.** Logged deliberately: the round trip consumed real review cycles, and the conclusion —
  a general SQL door is not worth its blast radius even behind admin auth — should not have to be
  rediscovered by the next person who wants one.


### 2026-09-04 → 2026-09-07

- **Workspace RBAC completed across slices 3, 5 and 6** (#1285 the Roles screen, drawer and role
  assignment; #1295 denial telemetry, the unassignment event and a lockout proof; #1302 the staged
  rollout ladder, observe mode and a preflight report), plus full RBAC enforcement with a default
  Platform User role (#1293) and all tabs opened to signed-in users (#1287). Rollout readiness is now
  shown in Roles (#1634).
- **A domain grants sign-in; a role grants privileges** (#1417) — the two had been conflated, so
  adding a domain effectively granted privileges nobody had assigned.
- **Suspending somebody now actually stops them signing in** (#1453). The suspension was recorded and
  not enforced: a suspended user retained a working session and could re-authenticate.
- **A cached permission denial outlived the permission grant** (#1617) — a user who was just granted
  access kept being refused until the cache expired.
- **HITL item owner isolation enforced** (#1633) and **a document's name scoped to the viewer's own
  runs** (#1596). Same class as the three unscoped routes found on 2026-09-02: cross-account leakage
  through an object that was never owner-checked because nobody thought of it as data.


## Feature: Local model benchmarking · #4609

- Added an ollama service to the local compose stack on a named volume rather than a baked
  image (#161), to find out whether a larger local model does better on the .docx surfaces ACP
  already drafts with. This is deliberately the opposite of `deploy/ollama/Dockerfile`, which
  bakes llama3.1:8b + moondream so a cloud container has no multi-GB cold start — that image
  exists because llava:7b + llama came to ~9.2GB and OOM-killed the container against an 8Gi
  Azure Consumption ceiling. Deployment and local development have opposite constraints.
- Fixed an ollama healthcheck that called a binary the image does not contain (#162).


### 2026-09-04 → 2026-09-07

- **The Remediation Evals Kit answers one question: which tier is cheap enough AND safe enough**
  (#1316). Run against two local models, **neither earned a category** (#1328) — reported as a
  negative result rather than quietly dropped.
- **The hosted ladder: three Claude tiers, zero criticals, 178× over budget** (#1373). The quality
  answer and the cost answer point in opposite directions, and both are on the record.
- **A dispatch-only evals job with a spend guard that refuses before it bills** (#1345), and one place
  to configure the model key — the evals now read the product's (#1347), so an eval cannot pass
  against a model the product does not use.
- **The adversarial review-loop eval set: 32 cases, a reviewer oracle and re-scan** (#1678), plus
  measured remediation model evidence (#1641), model provenance on conformance reports (#1644), and
  **criterion-level model rollout gates** (#1704) with a shadow-mode comparison of Claude against the
  current remediation lane, per criterion: enable / human-only / insufficient (#1673). This is the
  machinery that lets a model be turned on for the criteria where it is proven and left off elsewhere,
  rather than as one all-or-nothing switch.
- **A coverage band: a second case for every single-case category in the evals corpus** (#1705). A
  category represented by one case cannot distinguish a model that handles it from one that got lucky.
- **The first measured Claude run on the adversarial review-loop set** (#1721). Run 34135515960: 32
  cases x 3 repeats across Haiku 4.5 and Sonnet 5, 192 billed calls, $0.81, with the report JSON
  committed so the table can be checked rather than trusted. Accepted unchanged 51% / 62%, applied
  59% / 69%, cleared after re-scan 59% / 69%, **regressions introduced zero for both**, latency mean
  3.10s / 6.40s, $1.61e-03 / $6.79e-03 per call. Three findings matter more than the headline: the
  reviewer is load-bearing (both models produced proposals that would have regressed unedited — Haiku
  5, Sonnet 3, rules-only 9 more; all caught), the must-refuse cases separate the two candidates
  (Sonnet escalated the invoice-header and PHI cases 3/3 where Haiku proposed a mutation), and cost
  runs 161x / 679x over the kit's per-dollar target uncached. Recorded in place: 32 cases is a look,
  not a distribution, and Sonnet is nondeterministic here (0.66 / 0.75 / 0.66 accept rate), which is
  why the default is three repeats.
- **The Claude eval candidate's credential is now named correctly, and the workflow accepts either
  name** (#1709, #1717). Five dispatches of the adversarial set died at the key check with
  `ANTHROPIC_API_KEY` blank while a real key sat in the Dependabot store, then under
  `ACP_ANTHROPIC_KEY`. The docs claimed resolution took "`ANTHROPIC_API_KEY` or `EVALS_API_KEY`" —
  `AnthropicCandidate` reads the first and nothing else — and never said that a job declaring no
  `environment:` cannot see an environment-scoped secret. The workflow now maps either secret name
  onto the one the kit reads, and its error text names the *store*, not just the settings page that
  carries three indistinguishable tabs.
- **A guarded Sonnet remediation pilot** (#1714) — the provider path, settings surface and store
  wiring to run Sonnet on remediation proposals behind an explicit switch, with a pilot module and
  tests rather than a global provider swap.




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
- **ADR 0038 — pausable/resumable scans** (#495). Design for the deliberately-deferred Track A Pause control:
  a large scan can be stopped mid-run and resumed exactly where it left off, without re-reading the files
  already done. Reuses the scan's existing stop-and-checkpoint machinery so a pause loses no completed work,
  and calls out the one hazard by name — a paused scan must not be mistaken for a crashed one — with a test to
  guard it. Design only; the control itself was held back until this backend exists, rather than shipping a
  button that only looks like it pauses. Docs-only, not RULE_PATHS.
- **§12 "Confirmed technical contract" for the pilot deck** (#519). Gathered the confirmed facts about how ACP
  runs — where documents are processed, what stays on the customer's own infrastructure, how the GPU vision
  path works — into one contract section a customer's security reviewer can be handed, each claim cited to
  origin/main rather than to intent. Docs-only, not RULE_PATHS.
- **GPU/vision production-contract answers** (#521). Plain answers to seven production-readiness questions on
  the GPU/vision lane (the in-tenant Azure T4, the ollama-on-GPU path, what the pre-flight probe actually
  verifies), each cited to the code as it stands on origin/main rather than to plan. Docs-only, not RULE_PATHS.

- **ADR 0040, the independent verification gate, and adversarial fixtures** (#734, P4.1/P4.4/P4.5) — plus a
  sweep-corpus density and confidence-calibration script (#746, P4.2/P4.6).
- **Backlog reconciled against the source, twice** (#670, #678, #683, #686, #687, #715, #717, #678). #670
  marked eleven items done, each source-verified on 2026-08-24; #678 closed R10, R13 and P3.5. The pattern
  this repeats: `docs/TODO.md` drifts stale because shipping and closing are separate acts, so the log
  records the reconciliation rather than the individual strikethroughs.
- **Decisions closed with evidence** — P1.4 production quality met via RunPod `qwen2.5-vl` (#799); R11 load
  test PASS 2026-08-25 (#817); R12 GPU vision `zone=cloud` confirmed in prod, deploy #559 (#801); P3.1 closed
  after confirming the PDF engine was vendored by ADR 0029 and correcting a stale comment (#771); P0.10
  warning when `deploy.sh` uses shared Langfuse defaults (#798); a stale 2.4.4 PDF coverage reason corrected
  after P-21 shipped (#794). Blue/green deployment guide and the P-13–P-20 backlog written (#731); RunPod
  key-rotation runbook added (#754).


- **Five ADRs and a reliability PRD, written where the code disagreed with the plan** (#1022, #1046,
  #1053, #1056, #1071, #1085, #1096, #1126). ADR 0045 proposes controlled schema migration and says why
  a separate step is not enough (#1085); its §6 records that **the app and the worker deploy on
  different images and nobody sequences that** (#1096). ADR 0046 designs blob intake at Assess — design
  only, no code (#1126). The reliability-hardening PRD was verified against `main` and overlap-cleared
  before being written up (#1046). Role-specific connection budgets are proposed with **the arithmetic
  made executable** rather than asserted (#1056), the native entry points and what is actually isolated
  are mapped (#1071), and #1022 records two lessons that cost a session real work. #1053 records the
  .xlsx 2.4.4 credit gap *and the trap under its obvious fix* — the note that made #1076 possible.


- **A public Swagger document for the health/readiness/heartbeat API** (#917) — the endpoints an operator
  is told to check were previously documented only in the code that serves them.


### 2026-09-04 → 2026-09-07

- **The ADR index was missing 16 of 55 ADRs, and three cross-references pointed at nothing** (#1517).
  An index that silently omits a third of its entries is worse than no index — it is read as complete.
- **ADR 0053 framed the VPAT template decision and stopped citing ADR 0029 as its precedent** (#1514);
  the follow-up recorded that the terms were readable after all and answered its open Q2 (#1643).
- **Four stale status claims corrected, each of which read as current** (#1536 Phase 5's row said
  "planned" while two thirds of it served traffic; #1566 Phase 6's row said "planned" while the
  Section 508 edition was already offerable; #1626 the same row said "part delivered" after the last
  edition opened; #1518 two dated backlog notes reading as current). Plus a PRD whose heading and
  status line both named a stale phase (#1631), and a PRD claiming sub-headings "do not yet match"
  forty minutes after they did (#1671).
- `docs/TODO.md`'s coverage counts were 36/45/6 and are 37/44/6 (#1396); **31 of 70 catalog rules
  pointed at files that do not exist** (#1397); the chart rendered less than the plan promised (#1394)
  and the volume it asked for would have broken the model runtime (#1428); two output figures named
  the wrong thing (#1422); the 98.36% CPU figure is now cited rather than traceless (#1304).
- CLAUDE.md corrections: which writes the proxy refuses and who has to make them (#1384); a
  remote-tracking ref outlives the branch it describes (#1516); **"is it in production?" is an
  ancestry question**, not a tag comparison (#1547).
- The real-time remediation operations panel was specified before it was built (#1379, #1382, #1433),
  the coverage-and-adapters sprint backlog added (#1315), the database tier put in front of a proposal
  that ignored it (#1308), and the vision-adapter dependency marked shipped (#1276).
- **Five sites still described ACR export "Phase 5" as pending, and one of them reached customers**
  (#1708). `acr_export_preview.py`'s projection carried "The official ITI VPAT® template is integrated
  in Phase 5", printed in the notice above **every draft preview**, wrapped by the PDF and carried in
  the JSON — telling every reader a template file was coming when ADR 0053 (Option C, decided
  2026-09-07) had decided the opposite: match the structure, do not vendor the file. Corrected along
  with a module docstring wrong three ways, a seam docstring, a frontend comment claiming shipped tabs
  were unbuilt, and a test fixture carrying the false sentence verbatim. "not a VPAT" is retained,
  because the naming question is still open.
- **ADR 0047 still cited ADR 0029 as the licensing precedent ADR 0053 exists to retract** (#1710). The
  0053 retraction reached the two code sites that quoted the claim and missed the ADR where it
  originated — 0029 vendored a first-party analyser and contains no licensing or trademark reasoning
  at all. A repo-wide sweep confirms this was the last one. The bullet records what it used to say and
  why the correction missed it, rather than deleting the sentence: "fix the citations that quote it"
  is a checklist that completes while leaving the source intact.




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

- **Six criteria gained or upgraded detectors** (#766, #772, #774, #775, #785, #797, #667). 1.3.5 Identify
  Input Purpose for PDF and DOCX (#774); 2.5.3 Label in Name for PDF push-buttons (#775); 2.4.3 Focus Order
  for PDF promoted HEURISTIC → PARTIAL (#772); 2.4.4 link purpose extended to PDF vague phrases and xlsx
  cell-value labels (#766); 1.4.11 resolving `schemeClr` theme colours in docx/pptx shape contrast (#797);
  2.4.6 xlsx write-back applying approved sheet-tab and table-column labels (#785); and colour-only
  hyperlink detection in PPTX for 1.4.1 (#667).
- **Every assessed criterion × format pair now declares a remediation lane** (#676, #679, #683, #684, #696,
  #709, #789). Seven pairs in batch 2 (#679), seven pptx REVIEW-only pairs (#676), docx/pdf/pptx 1.4.1 and
  1.4.11 plus pptx 4.1.2 migrated out of `REVIEW_FORMATS` into the registry (#696), xlsx 1.4.1/1.4.11/4.1.2
  and pdf 2.4.3 declared ready (#684), 2.4.4×pdf and 3.1.2×xlsx declared with 2.1.2 removed from
  `REVIEW_FORMATS` (#709), and the 1.3.5 docx/pdf plus 2.5.3 pdf lanes declared (#789). All xlsx/pptx/pdf
  rule IDs are mapped to WCAG SCs — 61 SC pairs (#683). The gap this closes: a criterion could be *assessed*
  and silently have no declared path to a fix, which read to a customer as "we checked it" when nothing
  could act on the result.


- **Capability is reported as four levels on four denominators, never as one number** (#1026, #1034,
  #1057, #1092, #1094). #1057 is the finding that justifies the shape: three registered detectors —
  docx 1.3.5, pdf 1.3.5, pdf 2.5.3 — were written, imported cleanly, returned a real finding when
  called, and **nothing in the scan path ever called them**, because no caller invokes
  `rule_registry.evaluate`. A single headline number would have hidden that. The denominator decision
  was recorded rather than deferred again (#1034), reviewer-experience completeness is measured per
  (criterion, format) (#1092), two overstated precision claims were corrected (#1094), and the stale
  capability report regenerated (#1026).
- **pdf.reading-order, bounded honestly rather than claimed** (#1044, #1089, #1100). Recorded as unable
  to fire, with a watch on the engine that houses it (#1044); a third false positive — tagged reading
  order — covered (#1089); then implemented as a **bounded** capability with 1.3.2 explicitly left
  uncovered (#1100).
- **Reviewer guidance that says why *this* criterion matters** (#1062, #1088, #1091, #1099, #1102). The
  reviewer is told why THIS criterion matters, not why its principle does (#1088); the four criteria a
  menu path cannot resolve get real guidance (#1099); a finding says where it is and whether ACP can
  actually fix it (#1062). 1.3.5's heuristic false-positive rate was **measured instead of predicted**
  (#1091), and 1.3.5 applicability plus 2.5.3 were evaluated through real dispatch (#1102).


- **The three orphaned detectors were wired into the scan path** (#1209). This closes the finding #1057
  recorded: `docx_input_purpose_checks` (1.3.5, HEURISTIC/LOW), `pdf_input_purpose_checks` (1.3.5) and
  `pdf_label_in_name_checks` (2.5.3, PARTIAL/HIGH) now have thin wrappers in `office_structure.checks_for`,
  following the same pattern as `pdf_form_field_checks`. Detectors that returned real findings when called
  directly, and were never called, now run.
- **13 pptx/pdf lanes downgraded ASSISTED → HUMAN after tracing the write-back chain** (#1228, #1264). Every
  lane marked ASSISTED was audited end to end — proposer → approval store → `has_approved_values_to_write`
  → `apply_approved_values` / `apply_pdf_approved` → re-scan clears the finding. **Thirteen fail at step 4**:
  the write-back job is never enqueued, either because `has_approved_values_to_write` has no getter reading
  the rule id, or because the proposer carries `explain_only=True` and `apply_pdf_approved` has no routing
  for its locator type. This is a capability claim walked back on evidence — the honest direction, and the
  kind of correction the four-denominator model exists to make visible.
- **Capability matrix cells labelled for screen readers** (#1273).


### 2026-09-04 → 2026-09-07

- **pptx criterion coverage extended and then honestly walked back.** 1.3.1/1.3.2 (#1390, with a
  control that had no margin), 2.4.2/3.1.1 and the mislabel that declared them exposed (#1388),
  2.4.6/3.1.2 routing gaps closed (#1531), and the 1.4.5/1.4.9 image-of-text write-back chain wired
  (#1581) — then **downgraded to the HUMAN lane** (#1665) because the `descr` write cannot clear the
  OCR detector. The downgrade is the more valuable of the two commits: an automated lane that cannot
  prove its own fix is a false conformance claim.
- **xlsx 1.3.1 and 1.3.2 — every certifying pair now has ground truth** (#1392).
- **PDF**: veraPDF Phase 0 local PDF/UA-1 corroboration engine (ADR 0028, #1343); scanned-PDF Tier A
  detection gate with vision layout extraction (ADR 0027, #1360) and Tier B WCAG REVIEW findings from
  those layout descriptions (#1367); the 2.5.3 label-in-name detector extended to all AcroForm field
  types (#1354); struct-tree locator infrastructure for 1.4.5/1.4.9 in the HUMAN lane (#1624); and
  page-level OCR and vision reused during PDF remediation rather than recomputed (#1568).
- **Skip the LibreOffice round-trip when `soffice` cannot open a document, not merely when it is
  absent** (#1513) — the guard tested for the binary, not for whether it could do the job.
- **W4 criterion disposition**: a 20-test suite and P0 backlog ticks (#1330, #1334), with dispositions
  persisted to the `criterion_disposition` table (#1321). ADR 0041 added the auto-apply gate for
  validated 2.4.4 and 4.1.2 proposals (#1327).


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

- **P3.3 healthcare hardening** (#781, #655). Per-scan deletion to satisfy BAA erasure obligations, and PHI
  redaction in logs — the pairing matters, because an erasure guarantee that leaves PHI in application logs
  is not an erasure guarantee. Drive folder IDs are also no longer exposed in assess counts (#655).


### 2026-09-04 → 2026-09-07

- Owner isolation extended to HITL items (#1633) and to document names in run listings (#1596); shared
  scan credentials fail fast rather than falling back to an unscoped store (#1564). See the
  multi-tenancy section for the RBAC enforcement these depend on.


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
- **Stopped main CI runs cancelling each other, which skipped deploys** (#525). The CI concurrency group was
  cancelling an in-progress run when a newer commit landed on `main` — but `deploy.yml` fires on that run's
  `workflow_run: completed`, so a cancelled run never fired the deploy, and a merge could silently not ship.
  Scoped the cancel-in-progress behaviour so `main` runs are allowed to finish (and trigger their deploy)
  rather than being pre-empted. `Matrix-Note: none` — CI config only.

- **Stopped a collapsed scan from hijacking every view — selector half** (#520). The production
  monitor's `newest scan is full-size` probe fired on prod ("newest has 5 documents but a recent scan
  had 22"): every dashboard, report and selector defaults to the latest scan, so a degenerate small
  scan on top makes the whole app show a shrunken estate. `App.jsx` picked `list_scans()[0]` blindly;
  it now picks the newest scan that is NOT collapsed (new pure `pickDefaultScan`), falling back to the
  most recent full-size one. Mirrors the probe's own definition exactly — `files < 0.5 × the biggest
  of the last 10 siblings` — so the app's default and the probe agree on "collapsed." Conservative:
  it only skips a scan under half its biggest recent sibling, so a legitimately small estate (no
  larger sibling) is never hidden. Frontend-only; 7 tests. Hardens the SELECTOR, not the source.
- **Stopped a collapsed scan from being created — source half** (#522). The upstream cause: `local`
  scans the bundled test corpus, not the estate, yet was the SILENT default for a source-less scan
  (`POST /scans` `Query("local")` and the worker's `payload.get("source", "local")`) — so a stray
  request produced a small corpus scan that landed as "latest", the exact fingerprint. The scheduled
  sweep's fallback-to-local was already fixed; this closed the on-demand door: `source` is now
  required (a source-less request is a 422, never a corpus scan) and the worker fails closed
  (`FatalJobError`, mirroring the missing-`scan_id` guard). `?source=local` stays valid for dev/tests
  — only the silent default is gone. A caller audit first confirmed nothing relied on it (frontend,
  e2e and the one test-caller all pass a source explicitly); the full suite passed unchanged. Touches
  `api/routes/scans.py` + `api/handlers.py` — not RULE_PATHS.
- **Vision/GPU model readiness on `/readyz`** (#547). Extends the readiness surface (cf. #487 SMB) so a
  **missing vision model is caught before a scan runs dry** — the probe checks the model is actually present
  on the resolved GPU/vision path, not just that the host answers. Not RULE_PATHS.
- **CI reliability: don't let an empty merge commit or a silent red block deploys.** An empty merge commit
  was being read as a parser failure and blocking `main`'s deploy — fixed by asking `git` whether a commit is
  empty rather than enumerating the exceptions; and `main` going red is now **announced out loud** (a skipped
  deploy is otherwise silent). Pairs with the earlier CI cancel-in-progress fix (#525). CI config; not
  RULE_PATHS.

- **Blue/green cutover and a staging worker** (#749, #824, `c69ab809`, `4bf2dd57`). A standalone
  `blue-green.sh` zero-downtime cutover script (#749); a `start-staging-worker` workflow; and
  `environment:staging` added so the OIDC subject matches the Azure federated credential — without it the
  staging deploy could not authenticate at all. `ACP_DEPLOY_ENV=staging` is now overridden *after*
  `deploy.sh` runs on staging provisioning (#824), which had been silently reverting to prod values.
- **The deploy pipeline stopped losing ships to races** (#866, #867, #747, `bc9e8040`). The CI gate query
  retries to survive GitHub API indexing lag (#866) and handles in-progress CI when a deploy races a newer
  merge (#867) — together these were the cause of merges that looked green and never shipped. Auto-merge
  squashes when CI is green (#747), and an automated SSE smoke test now runs against staging after every
  deploy (`bc9e8040`, #820, with the script updated for the nested snapshot schema — `b346eb18`).
- **Worker capacity** (#645). Worker CPU and memory doubled with ephemeral storage added, after large-estate
  scans were being killed rather than slowed.


- **Ingress gating moved from "answers TCP" to "can actually serve"** (#1152, #1153, #1189, #1200). The
  readiness gate is wired into the production redeploy (#1153) and ingress gates on a replica that can
  serve (#1152). One clean poll is not an answer: the worker check is sustained and ACA is asked how
  many revisions are actually running (#1189), and a busy ACA is waited out rather than failing the
  deploy between two apps (#1200).
- **The worker tier split into roles, then the generic worker was retired** (#1106, #1124, #1125, #1133,
  #1142, #1172, #1174, #1183, #1184). The worker tier says which image it is running (#1106); Discovery
  and processing job claims are isolated by worker role (#1124), with Discovery given queue precedence
  and its own scaling (#1125); Assess and Remediate got dedicated lanes (#1133); Discovery capacity is
  released before Assess (#1142). The generic production worker was then retired from deploys (#1172)
  and the retirement finished (#1184), after #1183 checked which worker roles the deploy actually ships
  and stopped it expanding a retired one. #1174 verifies each worker service **by its own heartbeat,
  not by a key they all overwrite** — without which the roles are indistinguishable to the health check.
- **ACP Lite deployed as its own Container App** (#1122, #1129). A cut-down Discover/Assess/Remediate
  page served as a single static page from its own Container App beside `acp-app`, sharing the resource
  group, registry and Container Apps environment — and nothing else. The reasoning is the part worth
  keeping: adding a prototype page to the control-plane image means every Lite change rebuilds it and
  **restarts running scans**. Lite scales to zero, which is safe precisely because it holds no state;
  the control plane cannot. #1129 restored the production folder picker in it.
- **Auto-merge, corrected twice by evidence** (#1041, #1160, `7817e5ab`). A hold label that exempts a PR
  from auto-merge, actively enforced (#1041); unconditional auto-merge disabled as a stated TEMPORARY
  measure with the hold-for-review disable path kept (`7817e5ab`); and #1160 recording that **the
  documented recipe cannot work — the label is the real mechanism.**
- **Staging gained read-only validation and deadlock evidence** (#1039, #1048, #1167). A read-only
  staging Azure validation workflow with a separately gated scale test (#1039), plus staging diagnostic
  logging config and read-only deadlock evidence retrieval (#1048). #1167 then refuses to destroy a
  PostgreSQL database no test has proven is disposable — a guard added because the diagnostics work had
  made the destructive path reachable.


- **Deploy and sweep visibility, mid-window** (#890, #891, #906, #909). A `skip_ci_gate` manual-dispatch
  input added to staging (#890) and mirrored to production (#891); auto-merge fixed so it stopped silently
  blocking CI-on-main and the deploy (#906); and the scheduled sweep's outcome printed in the production
  monitor (#909), which had been running blind.


### 2026-09-04 → 2026-09-07

- **A portable deployment packaging contract and its tooling** (#1290), the ACP application Helm chart
  (#1309), and `acpctl` matured into something that can be trusted: `init` writes a deployment
  document that is valid when it is written (#1331), `doctor` makes two silent preconditions loud
  (#1319), and `status` reports health plus the drift check the document's own claim needs (#1324).
- **The Azure contract was checked against the running system rather than assumed.** Parity baseline
  derived and made to survive #1370 landing under it (#1375); the deployment timeline and **the half
  of a deploy Azure cannot see** (#1381); the two things the rebuild contract could not say about
  production (#1380); who makes the document true (#1386); cost at the customer's own rate plus the
  logs that say why a rollout failed (#1389). `/healthz` now names the commit it was built from (#1529).
- **A transition is not a current status** (#1378) and **"nobody is watching" is not "nothing is
  wrong"** (#1377) — two alerting defects where the absence of a signal was rendered as a healthy one.
- **Legacy bootstrap for OIDC deploys, in five attempts, ending in a verified one** (#1585, #1591,
  #1595, #1599, #1600): kept alive without caller stdin, validated as complete before Azure reports
  teardown status, and compressed/compacted to fit the exec channel. Only one verified legacy
  readiness bootstrap is permitted (#1585).
- **Staging is now isolated from production** (#1612 role workers, #1629 auxiliaries, #1623 an
  unsupported worker storage flag removed). A staging run reaching a production auxiliary is a data
  incident, not a test failure.
- **Capacity scheduling shipped through phases 1–4 and finished** (#1538, #1544, #1583, #1654): the
  scalers fixed, the schedule shown, published, and attributed to who asked for it, behind a
  staging-gated policy adapter. Work-hours autoscaling foundations added (#1642).
- **Active worker jobs are protected during deployments** (#1576), worker telemetry stays alive while
  draining (#1609), and **the worker registry stopped keeping every replica it had ever seen** (#1590)
  — the registry was accumulating dead replicas, which is what put 1000 dead names at the top of the
  Live Ops drawer (#1574).
- Connection budget corrected for the three-tier worker topology (#1298); the worker size figure now
  names the service it came from rather than "the worker tier" (#1312, #1322); the `WORKER_APP_NAME`
  default was removed because it named a retired app (#1317); the last three replica ranges were
  decided together and priced (#1459). A tab left open across a deploy showed an error for a page that
  was fine (#1565).
- **Capacity schedule loading fixed** (#1711) — the control-plane route and its frontend client
  disagreed, so the work-hours autoscaling schedule (#1642) could not be read back.
- **A pending CI run is cancelled too, so main's middle commits never shipped** (#1713).
  `cancel-in-progress: false` was introduced to stop rapid merges cancelling each other and the code
  comment recorded it as solved; it was not. A concurrency group holds one running plus one *pending*
  run, and a third arrival cancels the pending one regardless of that flag. Measured twice inside ten
  minutes on 2026-09-06 (CI 3545 and 3549, each cancelled within two seconds of the next run's
  creation, neither ever given a runner). `deploy.yml` requires `conclusion == 'success'`, and a
  cancelled run is neither success nor failure — deploy run 1330 refused main's tip outright with five
  merged PRs behind it. Main now gets **one concurrency group per commit**; PR refs keep a single
  group so a ten-push branch still supersedes itself. This deliberately reverses the earlier trade —
  runs on main are parallel and cost more runner minutes — because a commit that never deploys is the
  more expensive failure. The test **evaluates** the group expression against concrete contexts rather
  than grepping it for `github.sha`, which would pass for an expression that fixed main by breaking PR
  supersession.




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


### 2026-09-04 → 2026-09-07

- **Release became a real three-step workflow** (#1553) with the builder first (#1607), users led
  directly into it (#1543), a guided delivery workflow (#1537), destinations previewed before
  publishing (#1597), and named release packages and destinations (#1592). The Release destination
  workspace was polished (#1620), folder depth made explicit and release timestamps localized (#1638).
- **Structured release folders preserve the source hierarchy** (#1425) and corrected files download as
  one release package (#1588); released files remain selectable for download afterwards (#1567).
- **Release manifests made authoritative and tamper-evident** (#1481), a published revision exports
  from its snapshot and **refuses when the digest fails** (#1442), and **Release effects are reserved
  before provider writes** (#1692) so a partial publish cannot leave the record claiming a file that
  was never written. Partial Release failures are recoverable (#1559) and durable Release progress and
  recovery were restored (#1602).
- **Every assessed finding is now reconciled through Release** (#1647), with receipts bound to exact
  finding lineage (#1687), exact AI provenance shown before Release (#1656), finding evidence
  drill-down and report attestation exposed (#1658), and Conformance and Release snapshot identity
  aligned (#1670). A release that cannot name which finding each corrected file answers is not an
  audit artifact.
- Durable cross-run Release history added (#1608, #1615). Release exports aligned with canonical stage
  accounting (#1699) and synchronous Release execution canonicalized (#1695).
- **The guided Release delivery workspace completed** (#1718) — a persistent plan summary, a file
  selection step, configurable and hardened corrected-file download names, accessibility polish on the
  step panel, and the Release package preview mapped into the workspace capability map, across seven
  slices with backend package/preview tests behind them.




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
- **One remediation surface in the file drawer — the Auto-remediate card folded into the status hero**
  (#469, redesign Phase 1). The document drawer stacked two remediation cards: the ADR-0026 Assessment
  Coverage hero (coverage bar + "N issues need remediation" + a "Start Remediation" CTA) and, right below,
  a separate "Auto-remediate" card with its own CTA, its own time estimate, and a findings count that
  disagreed with the bar — two CTAs, two estimates, three counts, and the hero's CTA wasn't even the real
  action (the working "Remediate this file now" lived in the lower card). `AccessibilityStatus` gained an
  `actionSlot` that renders in place of its default CTA; the drawer passes its live remediation control
  (button + progress + result) into it, so status and action are one card with one CTA. The auto-fixable
  count is derived from the same `findingAuto` lanes the Findings list uses, so they can't disagree; the
  standalone reccard and its dead `REC_STYLE`/`MODE_LABEL` constants were removed. Frontend tests; not a
  RULE_PATHS change.
- **The R1–R12 redesign core, built as standalone modules and then mounted.** A `claude[bot]` pipeline
  landed the redesign as discrete, unit-tested modules: the work partitioned by **who does it** (R2) + the
  deterministic **batch** (R3); the **approval queue** (R5) and **verification state** (R9); the **manual
  lane** (R6, from the capability table); **what happened when a fix did not land** (R8); the **audit
  trail** (R10); **delivery** per configuration (R11) and **close-the-loop** re-verification (R12); and R7
  per-document progress. The #551 wiring then rewired `Remediate.jsx` around them and a follow-up mounted
  the per-item panels into the detail pane, so **all ten board components now render** rather than sitting
  orphaned. Frontend; not RULE_PATHS.
- **R20 — CSV companion to the remediation report** (#569). The report shipped PDF-only; this adds the
  machine-readable half (one row per document × criterion — found / changed-to / remaining), built from the
  **same `buildRemediationModel`** the PDF uses so the two cannot diverge, RFC-4180 quoting, and the PDF's
  honesty carried over ("time not recorded"; a `# PARTIAL` line when the fix list is capped). A "Changes
  (CSV)" button beside the PDF one; 9 tests. Taken as a non-overlapping slice after cross-session
  coordination. Frontend; not RULE_PATHS.
- **Removed the R4 "Preview one fix" stepper that shipped live** (#570, closes #568). R4 was reviewed and
  **dropped by Deva, confirmed by Jeremy** — but the bot pipeline had merged it as a standalone module
  (#560) and the mounting step rendered it in the live tab (`Remediate.jsx:947`). Filed #568 with the
  line-level evidence; the removal drops the import + render and deletes the module/model/tests (keeping R7),
  with the two shared source-sweep tests trimmed. A dropped decision, un-shipped. Frontend; not RULE_PATHS.
- **R18 — comments on a finding** (#573). A judgement call that two people disagree about should live
  *next to the finding*, not in a chat nobody reading it later can see. Adds an append-only discussion
  thread anchored to one finding (scan × file × criterion × instance) via a new `finding_comments` table
  and owner-scoped `GET`/`POST /scans/{sid}/comments` — the author is stamped server-side, never from the
  request body, so a comment can't be misattributed. The UI is a new `FindingComments` component mounted
  through the existing `renderDetailExtra` render-prop (the same additive one-line pattern as
  `DocumentAudit`), so the inbox model and apply/assignee flow are untouched. Honest states: nothing
  renders before the fetch answers, and the empty state says the thread is empty, not that the finding is
  uncontested. Table registered in `_ANALYTICS_TABLES` (reset-completeness). 7 backend + 5 frontend tests.
  Backend + frontend; not RULE_PATHS.
- **R19 — due dates on a document** (#586). The deadline half of "who does this, by when" — the sibling of
  the R17 assignee axis. A due date rides the same generic per-file `scan_decisions` store (`kind='due_date'`),
  so it is owner-scoped for free, one date per document, and needs **no new persistence**: the two decision
  routes just widen their allow-list, and `assessment_policy.due_dates()` / `overdue_files(decisions, today)`
  read it (overdue is strictly-before-today, correct for `YYYY-MM-DD` and full timestamps; due-today is not
  overdue). New self-contained `DueDate` component mounted via the same `renderDetailExtra` prop (reuses
  `saveDecision`, so `api.js` is untouched); shows an Overdue badge and — honoring the design's own caution
  that "a due date with no owner is a decoration" — warns when a deadline is set on an unowned document. A
  list-level overdue badge on inbox rows was deliberately deferred (belongs in the hot inbox the pipeline is
  rewriting; `overdue_files()` is the backend it will use). 7 backend + 7 frontend tests. `assessment_policy.py`
  is under RULE_PATHS (it holds the lane tables) but the change adds only workflow helpers, so the commit
  carries `Matrix-Note: none`. Backend + frontend.
- **R16 — fix-critical-first: found already shipped, not rebuilt.** `remediationInboxModel.sortQueue`'s default
  `priority` sort already orders by `SEV_RANK` (critical → serious → moderate → minor), then lane, then id, and
  the inbox defaults to it — so the backlog item was satisfied. Recorded here rather than duplicated.

- **Human-review workflow persisted and observable** (#732, #713, #723, #729, #764, #685, #695). An
  `in_review` status with `hitl.assigned` / `hitl.resolved` webhook events (#732); reviewer assignment
  persisted to the database rather than held in session (#713, #723); a completed human-review KPI block
  covering edited drafts and average review time (#729, R9). Two defects: `ReviewCenter` was **swallowing
  approval errors** so a failed approval looked like a successful one (#764), and a race in `listHitlQueue`
  re-surfaced in-flight items to a second reviewer (#685). `window.confirm`/`alert` replaced with a
  `ConfirmDialog` overlay (#695).


- **Review Memory and the house-style chip** (#996, #999, #1011). The Review Memory panel was wired up
  (#996, ADR 0021) and the "house style applied" chip built (#999) and shown on scan-time pre-drafted
  cards (#1011, ADR 0021 §E) — so a reviewer can tell a freshly drafted suggestion from a remembered
  decision.


### 2026-09-04 → 2026-09-07

- **The remediation run card now survives the things that used to destroy it** (#1413 leaving the tab,
  with one stream that survives with it; #1403 resuming the stream from the last event the browser
  rendered; #1462 reconnecting interrupted streams; #1461 hardened live-state recovery; #1601 the card
  shown on every tab; #1454 one card per navigation context; #1554 the activity pulse following it).
  A reviewer who navigates away and loses a running remediation is a reviewer who stops trusting the
  screen.
- **Live remediation state made truthful rather than merely animated** (#1512, #1521, #1473 durable
  structured progress that stops counting heartbeats as progress, #1534 live deltas, #1511 processed-document
  completeness, #1606 live throughput on the durable card, #1466 measured throughput and ETA, #1616
  reconciled finding counts). Three cards were lying in specific ways: one whose status line said
  "Complete" was headed ACTIVE JOB (#1542), the completed chip showed a job 93% through remediating
  (#1540), and the operator hold — a wait on a human — held a stream open that should have closed (#1523).
- **Reviewer throughput work**: visible-view bulk actions (#1451), restored scoped bulk approval
  (#1445), simplified guided decisions (#1465), simplified workspace (#1339), polished decisions and
  completion (#1344, #1356), collapsed audit trail (#1325), a narrow-screen layout (#1469), a compact
  status everywhere except Live Processing (#1556), one compact activity card (#1630), and the bulk
  popup replaced with an upper-right toast (#1541).
- **AI drafts are now separable from human work end to end** (#1605 classified from provenance, #1603
  reviewers can isolate AI-assisted drafts, #1659 remediation drafts linked to reviewer outcomes,
  #1662 the same for vision drafts, #1667 post-write validation outcomes recorded, #1680 each draft
  linked to its post-write validation including regressions, #1674 a refused write surfaced on the
  review card as `apply_outcome` from `apply.unverified`). #1674 is the one that matters most: a write
  the system could not verify used to look like a completed fix.
- Automation preview shows file impact (#1636) and confidence (#1618); the automation slider counts
  were reconciled with what remediation actually does (#1651). The remediation accessibility check was
  scoped to the workflow panel (#1522).


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

- **The "0 documents" failure class, closed across every surface that could report it** (#835, #836, #848,
  #860, #863, #868, #869, #870, #882, #636, #716). This was one symptom with at least seven causes, and each
  was fixed at its own layer: the headline read the wrong table (#636); `scan_runs` was created only *after*
  listing, so large-estate scans were falsely marked never-started (#716); the suspicious-zero guard
  disarmed on retry (#860) and needed hardening plus a sync-path conflict response (#869); a
  `phase=discovered` overwrite raced a conflict that had already written `phase=error` (#868); pre-ADR-0020
  scans had no `file_records` baseline to count (#870); the completion card gate did not accept
  `status='discovered'` as a durable Postgres fallback (#882); and two channels were reporting a false zero
  independently (#863). "0 files discovered" now shows the real estate total (#848), and a partial listing is
  surfaced as partial rather than as nothing.
- **Discovery at wide-estate scale** (#776, #830, #831, #826, #827, #880). Parallel BFS for Drive folder
  traversal — **up to 6× faster on wide estates** (#776) — with progress callbacks throttled to 2s intervals
  so the speedup was not spent on chatter (#830), resumable checkpoints (#831), `add_inventory`'s per-row
  inserts batched instead of looped through `execute()` (#880), and the lifecycle rule evaluator bulk-loading
  dispositions with batched writes (#826) after pre-parsing policy match conditions once outside the
  inventory loop (#827).
- **Discovery results became a dashboard rather than a number** (#819, #605, #615, #646, #849, #847, #855,
  #864, #865, #762). Age / size / folder distribution panels (#819), an estate-composition treemap and
  compliance funnel with real drill-down (#605, #616), and a flat `DiscoverCompleteSummary` card replacing
  the estate bar (#864, #865, #762). Two honesty fixes underneath: the *By file type* panel had been counting
  only scanned rows rather than the estate (#615), and OS metadata files (`.DS_Store`, `Thumbs.db`) were
  inflating the inventory (#646). Listing / Metadata / Classifying collapsed into one honest step (#847) with
  a live folder count during listing, not just files (#849).
- **Estate analytics, renamed twice and rebuilt once** (#728, #754, #757, #769, #701, #702, #777). The
  backend-enforced estate analytics tab shipped as *Admin Insights* (#728), was renamed *Estate Insights*
  (#754), rebuilt with KPIs / funnel / charts / data-quality panels (#757), and the adjacent tab renamed
  *Scan Analytics* (#769). Overview gained a stakeholder summary with an eligible-funnel step and real empty
  states (#702) and an estate progress panel (#701). P3.4 shipped Power BI export via Postgres read-only
  views and DirectQuery (#777).

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
- **Explicit units + one source of truth for the estate numbers** (#471, redesign Phase 0). The Assess
  results page showed "criteria" as five different things — 14 (agreed scope), 17 (tracked), 20 (document
  core), ~38 (traced-for-this-file), plus a "16" that was a numerator leaking into denominator position —
  each internally labelled but reading, unlabelled together, as disagreeing measurements. Rather than force
  the deliberately-reconciled panels to one number, three unambiguous fixes: the CoverageScorecard
  remediation tiles printed "6 / 8 / 1" with no denominator (`total={null}`) — now carry the same `/20`
  core denominator as the assessment tiles ("6 of 20 criteria"); the ConfidenceDashboard's "468 of 1,482
  criteria" is really criteria × documents, relabelled "criterion checks"; and the duplicate `DOCUMENTS_20`
  in `assessCoverage.js` (a second hand-maintained copy of the 20 core SCs) now derives from the single
  `documents20.js` set so "20" can't drift. Deliberately deferred to the visual phase: collapsing the three
  renderings of the same failure (pass-rate % / master ring / risk 0/100), and the hero frame that makes
  14/17/20/38 read as different questions. Not a RULE_PATHS change.
- **Decision-first KPI cards on the results view + drop the duplicate pass-rate** (#488, redesign Phase 2).
  AssessRunner's four result tiles became four decision KPI cards — documents needing action, findings,
  ACP-addressable (auto-fix), estimated human effort — every value read from `result` (→ `coreStats`, the
  one estate lens AssessRunner and RiskScore already share) so they can't disagree with the verdict banner
  or the "By WCAG criterion" table. The "pass rate %" tile was removed as a third rendering of the same
  estate failure the master-score ring and risk score already show; documents are now framed as the
  decision ("need action"), not a pass percentage. Effort renders through the labelled `effort.js` heuristic
  (`est.` + `EFFORT_BASIS`), never as a measurement. Browser-verified in SIM (139 findings = 57 auto + 82
  person, 57/139 = 41%, ~48.8 hrs — banner and all four cards agree). The master-ring / risk-score
  consolidation is a further follow-up. Not a RULE_PATHS change.
- **"Last modified" age distribution over the whole estate — the retention question** (#515 backend + #517
  frontend). Discover could say what share of an estate is assessable; it could not say how much of it anyone
  still touches — the retention question, the one with a delete decision attached. `modified` existed only
  inside `_sample_meta` (≤200 rows/status), so a histogram off it would be ≤200 files presented as the estate —
  "unsupported reads as passed by omission" wearing a new hat. So the bands are aggregated in `summarize()`
  over the FULL listing: four bands (<1y, 1–3y, 3–5y, >5y) plus an explicit **`unknown`** that is counted,
  never folded or dropped, so the bands sum to `discovered` and reconcile; banded across every file type, not
  just assessable formats (an old .mov nobody's opened in five years is exactly the delete candidate this is
  for); one injectable `now` for the whole listing so a long scan can't straddle a boundary (the exact shape
  that broke a frontend date assertion in this repo). Frontend refuses two quiet lies: a **missing** `by_age`
  (every pre-aggregation report) renders no panel rather than five measured-looking zeros, and the ordinal
  buckets are fixed youngest→oldest with "no date recorded" last, never sorted largest-first like the format
  composition. No new chart component — reuses `Bars` (ordered, null=not-measured). Not a RULE_PATHS change.
- **The Assess results redesign — one unit (the check), seven metrics, and no score** (#545, absorbs #543/#544).
  Nine panels leading with counts over four different unstated denominators became three levels (summary /
  file worklist / document) on **one unit: the check** (one criterion × one document), with every metric a
  slice that prints adding back up on screen. Definitions carry the weight: *documents assessed* names and
  excludes an unreadable file; *auto-fix* is deterministic only (AI drafts under human review); *unable-to-
  assess* counts checks that did not run, never files that passed; coverage is "14 of 17", never a percentage.
  The single **compliance score is removed** — a document with 40 findings awaiting judgement scored 100 and
  read "compliant", because a score cannot tell checked-and-passed from not-checked. Frontend; not RULE_PATHS.
- **Overview reconciled to one estate, with an action beside the number** (board 7). Every discovered file
  lands in exactly one bucket (reconciliation), the four headline tiles the board specifies replace the ad-hoc
  set, each assertion states its own scope beside the findings it qualifies, and a NEXT panel gives one action
  with its denominator next to it. The "assess?" question was dropped from Discover (it belongs to Assess).
  Frontend; not RULE_PATHS.

---


- **The 2026-08-28 wave: every Discover surface that could report a wrong number** (#903, #905, #907,
  #908, #910, #914, #918, #934, #940, #941). This continues the "0 documents" class from the previous
  window, but at the reporting layer rather than the data layer. `GET /scans` was blind to
  Discover-only scans (#910) — the root cause of "0 documents" on Discover *and* Assess — as were
  `/monitor/estate` (#907) and `/schedule`'s `last_at` (#908). A queued scan no longer shows 0 (#914),
  an untrustworthy run is explained rather than shown as 0 (#905), a queued scan this tab is not
  tracking live is explained (#918), and a stale "0 files inventoried" self-heals (#903). The
  completion card's failed/complete contradiction, worker-status wording and eligibility tooltips were
  fixed (#934), its totals reconciled with the rest of the screen (#941), and its eligibility
  breakdown collapsed behind a disclosure (#940).
- **Discover started showing the worker, not just the scan** (#916, #920, #921, #923, #924, #925, #926,
  #929, #930, #935, #936, #937, #938, #939). Worker availability — how many can pick up jobs (#925) —
  "Worker assigned" once a job is claimed (#926), a live SSE badge (#924), a green live badge when the
  scan's Redis job state is actively updating (#916), folder-level activity tracked during Drive
  discovery (#929) and shown on the card (#930), and **"worker online but queue not draining"**
  surfaced (#938) — the state that had previously looked identical to healthy. Two live bugs were
  fixed underneath it: a zero-workers boot race and an unbounded Drive socket (#935), with the
  remaining two socket call sites in #936.
- **Whole-Drive enumeration completed, and Discovery scope narrowed** (#1121, #1123, #1128, #1132,
  #1136, #1138). Whole-Drive enumeration finished (#1138) with readable folder breadcrumbs (#1136);
  durable Discovery capacity reserved and scan scope narrowed (#1121); whole-source scans reset with
  lifecycle buckets expanded (#1132); one Discovery queue status shown, warning on delayed pickup
  (#1123); setup made responsive with an unnecessary Drive listing removed (#1128).
- **A boot that fails is no longer an empty estate** (#1149, #1150, #1151, #1207). Boot reads are
  bounded and a failed load stops reporting as an empty estate (#1150); the scan enqueue is bounded and
  an unconfirmed submit is no longer called a failure (#1151); a stalled `/config` no longer strands
  sign-in forever (#1149). #1207 is the same distinction at the other end of the run — the user is told
  when a scan **found nothing**, instead of being shown a wall of zeros.


- **Discover's queued, retrying and failure states, 2026-08-27/28** (#892, #901, #902, #904, #911, #912,
  #913, #915, #919, #932). A distinct queued-state card (#901, PRD §16.1) and a retrying-state card with the
  backend signal it needs (#902, PRD §16.8); a "Cancel requested" acknowledgment on the Stop/Cancel button
  (#904); the **actual** discovery-failure reason surfaced instead of a static message (#919); stale
  failed/cancelled/interrupted banners suppressed while a new scan is busy (#915); the results table replaced
  with a queued placeholder for a new scan (#932); and a stale capacity notice cleared when an attempt fails
  (#892). The two "choose a folder to scan" flows were unified into one (#911), and raw scan data
  (`scope.enumeration` plus the decision log, with `run.status`) is now viewable on click for support
  debugging (#912, #913).


### 2026-09-04 → 2026-09-07

- Incremental discovery at estate scale (Phase 3, #1323); folder baselines rejected for Drive delta
  (#1284); readable folder paths shown in discovery (#1467); live Discovery state kept off historical
  scans (#1362); the live Discovery card owns its own status (#1573).
- **Discovery drifted in both directions and one script was fixing one while undoing the other**
  (#1530); the decision that Discovery is 4-8 is now stated in the script itself (#1533). A
  self-healing script that oscillates is harder to notice than one that plainly fails.
- Narrow scans distinguished from collapsed sweeps (#1520) — the two produce similar-looking counts
  and mean completely different things about coverage.


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
- **Discover asks only WHERE to inventory — formats/criteria move to Assess** (#532, PRD DISC-01). Discover's
  wizard no longer carries scan profiles, format cards, or the criterion × format matrix; those controls
  belong to Assess, where the deep evaluation actually happens. Discover is now a scope-only step (which
  source, which folders), matching the phase-1 exit contract "no format/SC controls in Discover" — a cleaner
  split between *what estate to catalogue* (Discover) and *how to judge it* (Assess).
- **Lifecycle-rules step — a plain-language rule editor that only ever tags.** A Discover step to author
  archival/deletion-candidate rules in plain language; it only **tags** (never moves or deletes), reads the
  lifecycle columns from the inventory route completely-or-not-at-all, and a companion disposition change lets
  a rule be **previewed before saving** and edited while it has not yet run.
- **Discovery results + a dated, exportable inventory** (#562). A discovery-results view (recommendations,
  acknowledgement, reconciliation); the results header now says **when the inventory was taken** (persisted
  from the discovery stamp, formatted — not the raw column, and not the assessment's time); and the inventory
  **exports as metadata-only CSV/JSON** with the snapshot instant. It also states plainly whether the
  inventory is the **whole estate** or just what a capped run found, and the ad-hoc single-file panel was
  removed on request. Several honesty fixes alongside: don't confirm a download that didn't happen; the scope
  screen sets a *discovery* boundary (it had said "assess"); the run's total counts what Assess enqueued, not
  what Discover listed.

- **Lifecycle rule authoring, finished end to end** (#604, #606, #608, #610, #611, #614, #617, #622, #626,
  #628, #631, #707, #726, #727, #738, #743, #751). The condition builder expanded to 10 fields, two of them
  new (#610); rules gained explicit priority, reordering and a conflicts report (#614); enabling a rule now
  previews its matches and asks first (#611), with a live match-count preview before save (#622) and inline
  expansion showing the matched files under the rule card (#707). A saved rule can be edited in place rather
  than only duplicated or deleted (#628, #608). Two correctness fixes matter more than the features: rules
  were **global shared records rather than per-tenant** (#606), and the decision log **attributed every rule
  action to "admin"** regardless of actor (#604). `disposition.evaluate()` now carries per-condition
  provenance (#727), per-file overrides write a reason and a dual audit entry (#617), the preview breaks out
  effective / superseded / exempted / unable-to-evaluate (#738, #743, #751), the audit trail filters by
  document (#631), and disabling or editing an enabled rule warns about tags already persisted (#726). The
  inventory CSV export had been dropping the rule, reason and any override (#626).


- **The lifecycle disposition review queue, built and then made honest** (#1148, #1154, #1155, #1163,
  #1164, #1165, #1169, #1170, #1171, #1173, #1175, #1179, #1180, #1182, #1192, #1205, #1206). An
  explainable Discovery lifecycle control plane (#1155), with Discovery formats and lifecycle
  disposition clarified (#1154). The queue's row became a cluster rather than a finding (#1148),
  grouped as its approval route already required (#1171), filtered to lifecycle candidates only
  (#1175), paginated for large lists (#1180), with its filters finished **including the two that cannot
  exist** (#1179). Approval was then made safe: a reviewer can approve an archival batch **without it
  meaning more than they meant** (#1170), and can see what approving a batch would do without doing any
  of it (#1192). Evidence is rendered in monospace (#1164), kept consistent with Discovery results
  (#1169), and a document's prior history is shown before this scan recommends archiving it (#1173).
  #1182 stopped recording an existing document as one that no longer exists. #1205 took the queue out
  of Discover, and #1206 says what the archive-vs-delete rule actually does — **all three outcomes of
  it**. #1165 tests the control plane the way somebody without a mouse uses it.
- **An archive that can be undone, and a recovery location that can be trusted** (#1187, #1190). Where a
  file came from is written down so an archive can be undone (#1190), and the UI says where a
  dispositioned file **can** be recovered and where it cannot (#1187). That distinction is what decides
  whether a customer will let the feature run at all.
- **The inventory CSV export stopped querying twice per row** (#1163).


- **A rule can no longer arm itself unattended, and shows what it rejected** (#1216, #1218, PRD Phase 3 §7.5).
  The preview returned every document a rule *selected* and not one it rejected — **and the rejected half is
  what a rule gets debugged from**. A rule selecting far fewer files than expected is diagnosed by seeing
  what fell out and on which condition, not by re-reading the count. The data was already in hand:
  `disposition.evaluate()` runs for every document in that loop and its failing condition was being discarded.
  #1218 then stops a rule that *changes files* being turned on unseen. Worth noting the discipline in #1216:
  most of the test bench already existed and was checked before building — the preview, the shared draft/saved
  path, `would_match` / `effective` / `superseded` / `exempted` / `unable_to_evaluate`, and the conflicts
  endpoint were all already real.
- **A cap on how many rows one disposition approval may cover** (#1213) — the blast-radius limit under the
  "approve a batch without it meaning more than you meant" guarantee (#1170).


### 2026-09-04 → 2026-09-07

- **An `in` operator, so a departed-employee roster is one rule** (#1363) rather than one rule per
  person, with roster matching added to the rule builder (#1368). **`not_in` is not the boolean
  negation of `in`** (#1365) — for a document with multiple owners the two are genuinely different
  questions, and treating one as the negation of the other silently mis-scopes the rule.
- Folder rules match on SharePoint (#1358); per-scan decision snapshot validation tests added (#1289);
  the remediation lifecycle log written (#1391); stages bound to frozen lifecycle policy inputs
  (#1492) so a rule edited mid-run cannot retroactively change what a completed stage decided.
- **The live-drift caveat has been hit, and `acp-remediate` is the instance** (#1526) — recorded
  against the ADR that predicted it rather than treated as a surprise.


## Feature: Observability — AI tracing and cost (Langfuse) · #4697

The scan / assess / remediate lifecycle was already traced, but the AI calls themselves were recorded as
cost-less, detached spans, and one decision surface had no trace at all. An audit first established the
state — 18/18 PHI tests green, coverage broad, the debt quality rather than absence — then four fixes
brought AI-call fidelity up to date and two extended it to the newest surfaces. Every new field is a
count / token number / model id / zone / cost — never prompt, completion, note, or filename (the PHI
invariant the redaction tests pin).

- **AI calls are Langfuse generations, not spans, carrying model + tokens + cost · #4705** (#368, G1). Added an
  `lf.generation()` helper (no-op when disabled) and switched `trace_ai_call` to it; token counts come from
  the provider results. They were logged as `.span()`, so per-call token usage and cost never reached the
  trace — only the `ai_calls` DB table had them.
- **Those generations nest under the file's own trace · #4706** (#368, G2). They were top-level `ai:{surface}`
  traces grouped only by scan session, so a file's Discover/Assess/Remediate trace never showed its own
  model calls; now they hang on `_trace_id(scan_id, file)` when known, with session grouping preserved.
- **Provider / zone / cost carried into the trace · #4707** (#368, G3). `ai._trace_ai` already computed them for the
  `ai_calls` row but the `lf` signature dropped them at the boundary; widened so trace and ledger agree.
- **Remediation span carries fix / skip counts · #4708** (#368, G4). `remediate_span` recorded only the Drive URL;
  the per-rule applied/skipped counts already existed in `_remediate_file` and are now passed through.
- **Cloud-vision token usage surfaces as generation `usage` · #4709** (#372, N1). Widened `providers._result` and
  each adapter (Azure, OpenAI, Anthropic, RunPod, Ollama) to carry prompt/completion tokens, threaded
  through `ai.py` — so cloud-vision generations carry real token usage, not just cost.
- **The disposition / pending-approval queue is now traced · #4710** (#371, N2). `routes/disposition.py` was the one
  untraced decision surface; a new `trace_disposition_decision` (status / action / policy-id / `reason_chars`
  count / HMAC doc label) mirrors the HITL decision span at every point a disposition is recorded.
- **Per-file traces carry the document + assessment result, not an empty shell · #4711** (#403). Every trace in the
  Langfuse session view read "no input or output": `file_trace` set a name/tags/metadata but never
  trace-level `input`/`output`, and only the child spans carried data — which the session LIST view does not
  surface (the $0.00 cost is correct: deterministic local checks have no per-token cost). `file_trace` now
  sets `input` = {redacted document label, format}; a new `file_assessment_result` sets `output` = score /
  conformant / level / failing WCAG criteria + counts, called per file in `ensure_assess_trace`. Strictly
  structured (docs/audit-langfuse-phi.md) — no document content, no raw filename; a test asserts the data
  lands AND carries no free text.
- **Traces gain a PII flag, remediation status, and the full per-check breakdown · #4712** (#406). Extends #403's
  trace output with `checks` = the whole {PASS/FAIL/REVIEW/NOT_EVALUATED: count} breakdown (not just
  failures, from the `get_scan_traces` rows already fetched); `pii` = {flagged, types, findings, critical}
  where `types` are CATEGORIES (`us_ssn`, `email_address`) — the same `sensitive_data_types` the PII span
  already emits, never a value; and `remediation` = {remediated, written_back, published} booleans off the
  file record. New kwargs optional (backward-compatible); the category-not-value invariant is pinned by
  test, and the no-free-text / redacts-filenames guards stay green.
- **Upgraded the deployed Langfuse v2 → v3 so the Session view scales · #4713** (ops + #447). With #403/#406
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
- **View a document's Langfuse trace INSIDE AccessOps, with no Langfuse login · #4714** (#454). The "📊 View
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
- **View a whole scan's traces INSIDE AccessOps — the session view (#459, follow-up to #454) · #4715**. The
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
- **Browser-verified the session view end to end · #4716** (no commit — testing, 2026-08-19). Drove the merged
  `origin/main` build in SIM mode and confirmed at the DOM: the Overview "📊 trace" chip opens the in-app
  `SessionPanel` (accessible name *"…inside AccessOps (no Langfuse login)"*); its rollup reads 3 documents /
  2 assessed / 1 conformant / 75 avg / 1 with-failures / 1 with-PII, with a document showing the honest
  *not assessed* state; clicking a row drills into the file `TracePanel`, which renders the corrected shape —
  failing criteria `1.1.1 ·1` / `1.4.3 ·3` (the dict that had shown nothing before the #454 fix) and PII
  categories `us_ssn` / `email_address` (no values). No console errors; no operator email in the UI.
  Verified via a standalone vite server from a throwaway `origin/main` worktree, because `preview_start` is
  pinned to the shared checkout — which is 47 commits behind and holds another session's uncommitted
  delivery-log work, so it was deliberately left untouched (see the "preview root" note in CLAUDE.md).
- **The operator email is out of every Langfuse trace NAME · #4717** (#506). The trace name is the label shown in
  Langfuse's trace/session LIST — a wider-access surface than the app — and it led with the signed-in
  operator's email on every trace (`jeremy_acp@…onmicrosoft.com · doc-…`, `devamovate@gmail.com · doc-…`,
  confirmed on live prod data). An identity leak distinct from the PHI/filename guards (an operator email is
  not a patient name, but it has no business in a shared observability list). Fixed at every name site — file
  trace, scan, assess, discover; segregation BY operator stays available through `user_id` and the `user:`
  tag (both filterable), which deliberately keep it. Made the names legible while there: the per-file trace
  is named for the redacted label, upgraded by `file_assessment_result` to `<label> · ✓/✗ <level>` once
  assessed, and a `format:` tag was added so the native UI can filter by document type. 79 Langfuse tests
  green; not a RULE_PATHS change.
- **Cross-scan document history — "this document over time" · #4718** (#507). The session view groups a scan's
  files, and Langfuse's own UI groups by session too, so neither can answer "how has THIS document trended
  across scans?". Every file trace already carries a `file:<label>` tag, so that question is exactly the
  traces with that tag (verified against the live v3 API before building). `lf.fetch_document_history(label)`
  queries the tag and returns the document's trace across every scan, newest first, PHI-safe (label used
  as-is, never re-hashed); `GET /scans/{sid}/trace/file/{file}/history` serves it; a `DocumentHistoryPanel`
  renders a score trajectory (sparkline + "▲ +N since first scan") and a row per scan, each drilling into
  that scan's trace via a callback (no import cycle with `TracePanel`). Backend + frontend tests; not a
  RULE_PATHS change.
- **Live per-file assess scores on the trace as a scan runs + file-level severity · #4719** (#518). Two Langfuse
  logging fixes (P0 from the polish list). (1) A file's score / conformance / failing criteria / per-check
  breakdown now lands on its trace the moment it's scored (`_emit_realtime_file_assess`, right after
  `save_file_result` persists), not only in the finalize batch — mid-run traces read empty before, which was
  the blind spot debugging the live cold-start SharePoint run (#513). The finalize pass still upserts the
  complete record (PII, remediation); both share `_emit_file_assess`, so real-time and finalize can't diverge;
  best-effort, no DB reads when tracing is off. (2) File-level SEVERITY so problems stand out in the trace
  list, not just the per-rule children: `assess_span` is ERROR for a non-conformant file / WARNING for
  non-blocking findings / DEFAULT when clean, and a file that couldn't be assessed (parse/fetch error,
  unreadable, or the #513 per-file timeout) gets an ERROR span with reason only, never content. Not a
  RULE_PATHS change.
- **Removed the dead scan/assess-trace functions superseded by the per-file model · #4720** (#524). The pre-per-file
  scan/assess tracing API (`scan_trace`, `error_span`, `file_span_for`, `open_assess_trace`,
  `finish_assess_trace`, `finish_scan_trace_by_id`, `finish_scan_trace`) was orphaned when `4b0ebce3` moved
  tracing to one-trace-per-file — that commit removed every call site but left the seven functions behind.
  Re-verified zero live callers across `api/`, `scripts/`, `tests/` on origin/main with word-boundary grep
  (counting callers, not substrings — `scan_trace` appears inside `finish_scan_trace_by_id`, `finish_scan_trace`
  inside its own `_by_id` wrapper), confirmed with the thread owner that `finish_scan_trace` wasn't being kept
  as deliberate public API, and removed all seven plus the two dead section-header comments and a docstring
  reference to the deleted `finish_assess_trace`. Trimmed the one test that exercised them, keeping its live
  `discover_run_trace` no-email guard. −133 lines; full backend job green (`api/lf.py` is not a RULE_PATHS
  file, so no Matrix-Note). The live per-file model is untouched.

- **Reproducibility metadata on every AI call** (#761, #763, #693, #758, #791). `temperature` and
  `prompt_version` columns added to `ai_calls` (#761) and `prompt_version` wired at all `ai.py` call sites
  (#763, P4.7); reproducibility metadata attached to proposals and judge output (#693). The provider now
  **warns loudly when `runpod_serverless` silently falls back to local Ollama** (#758) — the failure mode
  where quality drops with no signal — and the WARNING R2 log paths are pinned in `active_vision_provider`
  (#791).


- **Langfuse trace routes scoped by owner; raw email replaced with an HMAC key** (#1202). All eight
  `/scans/{sid}/trace/...` endpoints now resolve the authenticated owner from the request and look the
  scan up owner-scoped, so a request for another owner's scan returns 404 rather than leaking trace
  data — and the two `/exists` endpoints that had **no ownership check at all** guard through the same
  lookup. Operator email had been written to Langfuse both as a `user:{email}` tag and as `user_id`;
  it is replaced by a stable, irreversible HMAC using the same salt and algorithm as `_doc_label`, so
  the observability store holds no PII. `fetch_document_history` now takes an owner key and filters on
  `owner:{key}`, which is what stops cross-tenant document history being returned.


### 2026-09-04 → 2026-09-07

- **Honest cost transparency in Live Operations** (#1349), with **every missing cost signal explained**
  rather than rendered as zero (#1580), and **Azure billing actuals read from Cost Management** (#1586)
  — previously never called live, so the displayed cost was a model, not a bill.
- Azure Monitor's full metric set delivered over SSE with provenance on every value (#1350); metric
  windows sent as query-safe UTC (#1409). Grafana renders, and the image learns to split its own DSN
  (#1434).
- Telemetry endpoints reclassified as credentials rather than collectors (#1438).


## Feature: Scan-run experience — live progress and transparency (Track A) · #4696

The scan progress panel rebuilt from an implementation-centric spinner into an outcome-oriented,
transparent view of a running scan. Six merged slices; the owning session designed the "Track A" program
(alongside the Track B pipeline ADR below) and logged the #459 session view, so these scan-progress slices
are picked up here. Unbound Feature — no ADO id assigned yet; rebind if the program has one.

- **Per-file wall-clock safety net so one stuck document can't stall a run · #4721** (#513, reliability — not a
  Track-A slice). A live prod SharePoint assess sat at "Opening & assessing 0 of 22" for minutes. The
  analyse path is already well-bounded (download 120s, .NET office CLI 180s, OCR capped at 30 images) and no
  vision AI runs during assess — so this was cold-start + slow local CPU, not a hang. But "each sub-call is
  bounded" is not "the file is bounded": any step that ever slips its own timeout, a retry loop, or a future
  analyser added without one lets ONE document hold its worker forever, which with a small pool stalls the
  whole scan at 0/N. `_analyse_and_persist_one` now wraps its work in a per-file cap (`ACP_SCAN_FILE_TIMEOUT_S`,
  default 600s; 0 disables): past the cap the file is recorded as an error and the worker freed, so the scan
  always drains and finalizes. Safe against the finalize trigger (the caller's `count_files_done` runs after
  it returns; the error row counts toward the total, so a timed-out LAST file still finalizes; `save_file_result`
  upserts, so a late orphan thread just replaces the row). Diagnosed live via the Langfuse traces — which also
  surfaced that per-file scores land only at finalize, so mid-run "0 scored in Langfuse" is expected. Tests;
  not a RULE_PATHS change. It is a safety net, explicitly NOT a speed-up — a cold, image-heavy local-CPU scan
  is slow because the work is heavy; the speed levers are the in-tenant GPU AI lane and worker concurrency.
- **Outcome-oriented progress line · #4722** (#452, slice 1). The live line was implementation-centric — "Reading
  files · 145/250 · Document2.pptx" — naming one worker's current file while the fan-out processes many at
  once, so the filename was never an honest signal. Replaced by a pure, tested view-model
  (`assessmentProgress.js`) that turns the live payload into how much is done, how fast, and how long is
  left — a statement about the **run**, not one worker.
- **Live outcome chips · #4723** (#455, slice 2). Adds WHAT is emerging from the run — "97 passed · 23 need review ·
  7 failed · 105 processing" — streamed as files land. No backend change: `get_scan`'s run summary already
  carries certifiable/uncertain/error derived live from `file_records` (the same source `finalize_scan_run`
  aggregates), so the live chips and the final numbers cannot diverge.
- **Expandable "Processing details" table · #4724** (#458, slice 3a). A collapsed-by-default per-file table — each
  landed file with its format, result (Passed / Needs review / Failed / Queued) and score, filterable by
  All / Findings / Failed / Completed. Transparency for technical users without forcing everyone to watch a
  scrolling event log; fed entirely by the `file_records` that already stream.
- **Live scope funnel · #4725** (#460, slice 3b). Answers, inline and mid-scan, why a 250-file selection assesses
  fewer: "250 discovered · 214 assessable · 25 metadata-only · 11 unsupported · 5 couldn't open". Reuses the
  three-denominator inventory (`estateFunnel.statusRows` over `inventory.by_status`) — the SAME numbers
  EstateCoverage shows on Discover/Overview (#4597), never a second count that could disagree; `blocked`
  (password-protected / couldn't-open) surfaced separately since those files are eligible.
- **Folders as step 1 of the scan wizard · #4726** (#461). `ScanScopeWizard` owned the evaluation scope (criteria +
  formats) but never asked WHICH folders — folder choice lived only on the Sources card, so the wizard tuned
  ~50 checks without saying which half of the Drive they applied to. The folder step now goes **first**,
  seeded from the source. The load-bearing decision is the precedence rule: the card holds a folder set per
  **connection**, the wizard chooses one per **run**; the card seeds the wizard (so they agree unless
  diverged), a change applies to THIS run only, and write-back to the card is an explicit tick shown only
  once they differ — closing the 2026-07-30 config-vs-run boundary-mismatch class one level up.
- **"Notify me when complete" · #4727** (#463, slice 3c). The scan runs server-side and the banner is non-modal, so
  a user could always work elsewhere; this arms a browser notification that pings the outcome when the scan
  finishes ("145 of 250 assessed · 23 need review"). `scanNotify.js` asks permission once, only on opt-in.
- **Three-step scan wizard with progressive disclosure · #4728** (#470). The scan modal was a folder selector, scan
  configurator, WCAG matrix and engine panel all at once; #461 put folders first but *inside* that same dense
  panel, which made it worse. Rebuilt as **three steps — Drive locations → Formats & criteria → Review** —
  folders first because they decide which estate is judged, criteria only how each document in it is judged
  (asking criteria first invites tuning 53 checks over the wrong half of a Drive).
- **Two-column folder browser inline in step 1 · #4729** (#472). Step 1 embeds the picker — tree on the left, CURRENT
  SCOPE on the right, both visible at once — replacing the "Choose folders…" link into a modal. One
  implementation, two layouts: `FolderPicker` grows `layout="inline"`; the Sources card and Discover keep the
  modal. Adds a folder-scoped, honestly-labelled filter box.
- **Reuse a recent scope, symmetric criteria write-back · #4730** (#473). Step 1 offers the boundaries this user has
  **actually run**, derived from `scan_runs.scope` rather than a new saved-scopes store — a run's frozen scope
  is a record of what WAS covered, and only that can be re-offered. Runs with no recorded scope are refused
  (NULL is unknown, and applying unknown applies as *everything*), as are cross-family scopes and the wizard's
  own default; carve-outs carry through by id, labelled, not dropped.
- **Review step reports what this exact scope covered last time · #4731** (#474). Deliberately **not** a live pre-scan
  estimate: under ADR 0020 a Discover run *is* the listing, so an estimate is nearly the operation run twice,
  and it would put a second number for the same estate on screen under a different cap — the 2026-07-30 defect
  again. Instead the review step reports a number that was **measured** — what this exact scope covered on its
  last run.
- **Per-stage timing instrumentation (ADR 0037 Step 0) · #4732** (#467). The measure-first first step of the Track B
  pipeline design: `stage_timing.py` (pure — `ScanTimings` monotonic-clock accumulator, `merge_rollups` /
  `bottleneck` / `summarize`) times each file's scan by stage (download vs analyse) into its own
  `file_stage_timings` table, surfaced as a per-scan rollup (totals, per-stage average, bottleneck stage). A
  strict **side-channel** — every function is total (malformed input dropped, never raised), so timing can
  never disturb the scoring path it measures. No behaviour change; it exists so the staged speed-up is tuned
  from real numbers, not guesses.
- **`read_timings.py` — read a scan's per-stage rollup · #4733** (#478). A stdlib-only CLI over `GET
  /scans/{id}/timings` (signed-in session token) that prints where a scan spent its time — download (I/O) vs
  analyse (CPU + GPU) — bottleneck starred, so the next Track B step (splitting the bottleneck stage into its
  own bounded pool) is chosen from data. Companion to #467; `--json` / `--provider` flags, most-recent scan
  by default.
- **Honest folder sizes and exact carve-out state in the picker · #4734** (#512, wizard-review item 4). Each folder
  now shows a real item count only where the source can actually report one — SharePoint's `folder.childCount`
  — and shows nothing where it genuinely can't (Google Drive's `/folders` returns id + name, no count),
  instead of a reassuring invented "~120 files." A carve-out (excluding a child of an included folder) records
  its ancestor on the exclusion, which makes "included, with something carved out" an exact fact the drill-only
  picker can state without a whole-tree walk; everything else stays binary, because an unexpanded folder with
  unknown descendants is "not looked inside," not "partially selected." `indeterminate` (no HTML attribute) set
  via ref and mirrored to `aria-checked="mixed"`.
- **Folder-load failures are recoverable and classified, not a raw Graph error · #4735** (#511, wizard-review item 2).
  A failed folder list used to dump `Microsoft Graph error: 400 Bad Request` with an internal URL and drive id
  on screen — reads as broken, leaks internals, says nothing to do. The cause is now CLASSIFIED, not assumed:
  401/403/expired → "needs to be re-authorised" + Reconnect; 400/404 → "moved or deleted," explicitly NOT a
  reconnect prompt. The load-bearing judgement: the obvious rewrite ("your connection may need refreshing")
  would have been *actionable and wrong* here — the 400 came from a URL we built ourselves (#501), not an
  expired token — so an invented cause is worse than a stated one (same family as #483's "stop guessing
  unreadable"). No ids or URLs surfaced.
- **Scope correctness: composite folder ids split, empty folders don't mean the estate · #4736** (#501 + #502). #501 —
  the picker sends SharePoint back a composite `drive::folder` id; the download path now splits it so SP files
  are addressed correctly. #502 — an empty "Specific folders" selection was silently applying as the WHOLE
  estate (unknown → everything, the 2026-07-30 defect class); it is now an explicit empty scope, not a
  wildcard.
- **Wizard step 1 leads with the decision; the review step names the format population · #4737** (#509 + #514,
  wizard-review items 1/3 + a labelling fix). #509 — three "recent scope" cards sat above the mode selector,
  a scan-history browser in front of the decision offering a competing set of scope answers; now a collapsed
  `<details>` placed AFTER the selection (they all read as duplicates only because every recorded run was
  entire-source), and a band of single-fact header chrome removed. #514 — the review step listed "Formats:
  DOCX, XLSX, PPTX, PDF" next to a "22 documents" count drawn from a different population; a scan has three
  populations (everything discovered, the supported document types, the formats chosen — the only ones judged
  against WCAG and remediated), and the bare list next to the wrong count invited the reassuring guess "all of
  them." Now stated plainly (same honesty family as #479/#483/#491/#502).
- **The Live Assessment running screen — an authoritative, reconciled view of a scan in flight** (#553, #555,
  #556, #557, #561, #563, #566, #567; Live Assessment Experience §8). An authoritative live-run snapshot
  contract (#555) with a worker / queue / lane block (#553/#556) wired and mounted into the running screen
  (#557); a **findings-so-far** KPI reconciled to the final certification, with an honest "so far" qualifier
  on provisional counts (#561/#563); **rolling throughput + a calibrated ETA range** (#566, PRD 4.2/4.3); and
  a **server-tailing SSE event stream** over the snapshot (#567) so the screen updates live rather than
  polling blind. Turns "it's running" into how much is done, how fast, how long left, and what's emerging —
  the same numbers the final report will show. Backend + frontend; not RULE_PATHS.

- **The durable job queue, built out to ADR 0004 in one push** (#805–#814). The scan path stopped being a
  session-scoped thread and became a real queue: scan and job committed in one transaction (#806, with the
  scan row pre-created so `startScanQueued` returns a usable ID first — #805), an immutable input snapshot
  captured atomically at enqueue (#807), idempotent `disposition_audit` writes (#808), `SKIP LOCKED` claims
  with an inspectable `lease_expires_at` (#809), typed retry policies that classify the error and apply
  per-class backoff (#810), cooperative durable cancellation via `cancel_requested_at` (#811), a
  reconciliation sweeper for expired leases / exhausted jobs / orphaned scans (#812), and per-folder
  checkpoints (#814). The failure this prevents is the one the log kept recording all month: a scan whose
  worker replica died left no trace anyone could act on, so the run hung at 0/N until a human noticed.
- **Single-flight scans — supersede, don't race** (#841, #845, #607, #612, #871, #881). Two runs for one
  owner could interleave and the loser would overwrite the winner's results; worse, #845 found a *superseded*
  scan was being cancelled, and its real results then rendered as "0 documents". Cancellation now reaches a
  queued scan before any worker claims it (#612) and an outstanding job as well as `status='running'` (#881);
  a scan whose replica died is detected rather than hung on (#607); and a stale `active_discovery_guard` row
  is reclaimed instead of blocking every subsequent scan forever (#871).
- **Live progress that survives a dropped connection** (#840, #842, #843, #844, #886, `cbb6687f`). An
  EventSource progress stream now covers all scan paths (#842) on an authenticated client — the unauthenticated
  one was generating a stale-`job_id` 404 storm (#843). Job state moved to atomic Redis `HSET` with update
  coalescing and a scan-ID-based stream (#840); sparse Postgres checkpoints back it with adaptive
  SSE-fallback backoff (#844) so a client that loses push degrades to polling instead of going silent. A dead
  push now shows an explicit reconnecting freshness state (`cbb6687f`) rather than a frozen number, and a new
  scan surfaces without a page reload (#886).
- **A read-only preflight before a scan starts** (#846, #839). `POST /discovery/preflight` returns
  Ready / Degraded / Blocked, and `/readyz` warns ahead of the durable scan path (#839) — so a scan that was
  always going to fail on a missing Drive token fails at the button, not forty minutes in (#854).
- **Worker and queue transparency in the UI** (#818, #664, #658, #825, #822, #837). A `WorkerCard` with
  progress, speed and ETA during active phases (#818); a structured worker status strip with an honest
  activity timestamp (#664); stall detection and smart defaults (#658); and the alarming red health banner
  replaced with an amber *reconnecting* notice (#825) — red now means confirmed failure, not a slow poll.
  Workers back off on claim-time DB errors instead of hammering at poll cadence (#837).


- **ADR 0042: a durable scan-lifecycle event log, with SSE kept as the live transport** (#959, #965,
  #970, #974, #980, #982, #986). Landed as four no-caller-first PRs — the `scan_events` table and its
  two accessors, unused (#965); the lifecycle transitions emitted into it (#970); `GET
  /scans/{sid}/history` and the run-history panel that reads it (#974); the discover stream's not-live
  fallback frame filled from the event log (#980). ADR 0043 records the SSE-resume decision:
  **Last-Event-ID rejected, history-on-reconnect adopted** (#982). `GET /scans/{sid}/events` is
  recorded as deliberately unconsumed with a guard test (#986) rather than left looking like dead code.
- **Queue-pickup estimates on all three tabs** (#1000, #1002, #1004, #1006, #1087, #1090). A
  queue-pickup-estimate service (#1000) wired into Discover (#1002), Assess (#1004) and Remediate
  (#1006). Two corrections followed: the estimate now asks about the scan **just submitted, not the one
  on screen** (#1087), and a queued run's age comes from the server's timestamp or says it is
  unavailable (#1090) rather than being inferred from the client's clock.
- **Stale-while-revalidate across Overview, Assess and Monitor** (#947, #960, #962, #971, #977, #985,
  #987, #988, #989, #990, #997). A server-generated Overview snapshot cached per scan (#960) behind one
  `GET /workspace/bootstrap` request (#962), wired into App.jsx's initial load (#971); SWR then shipped
  for Overview (#977), Assess (#987) and Monitor (#990). Discover stopped showing misleading 0s before
  the scan payload had loaded (#988); the initial-load chain is instrumented with **real timing, not
  inferred timing** (#989); the load screen is parallelized and narrated (#947); ETag/If-None-Match
  conditional fetch was added to `GET /scans/{sid}` (#997); and two Overview cache-invalidation gaps
  found in audit were fixed (#985).
- **Assess progress that survives you looking away** (#1063, #1064, #1103, #1135, #1137, #1143, #1146).
  Durable per-file Assess progress (#1137) with live Assess and Remediate refresh (#1143); a run's
  elapsed time taken from the server so looking away does not reset it (#1103); active assessment
  status consolidated (#1135); stale Assess results hidden during new runs (#1146). Two honesty fixes
  underneath: Assess had been **naming one document as "the file being processed"** while processing
  many (#1064), and its progress bar counted against a different total from its own caption (#1063).
- **Monitor and Azure capacity became evidence rather than a status light** (#953, #954, #957, #958,
  #968, #969, #975, #983, #1028, #1032, #1035, #1036, #1037, #1054, #1059, #1065, #1086). Azure
  capacity evidence — current replica count, CPU/memory per worker (#953) — brought into Monitor →
  Workers & Queue (#954), with revision health and draining replicas (#957), revision traffic split
  (#968), a deploy/revision history view for the worker Container App (#983), deduped polling with a
  visual gauge (#969), and a stated reason when Azure Monitor metrics are unavailable (#975). A
  diagnosis layer turns worker and Azure signals into a ranked "here's likely why" (#958). Dead-letter
  incidents are aggregated by affected runs, attempts and time span (#1036), and the misleading "0
  workers" headline clarified (#1032). #1054 replaced five private polling loops with one shared `GET
  /jobs` subscription; #1065 shows the age of the queue data rather than the age of the subscription;
  and #1086 stops the queue claiming "empty" and "zero workers" **before it has read anything**.


- **Assess and Discover instrumentation, 2026-08-27/28/29** (#883, #887, #893, #895, #922, #927, #928, #933,
  #950). A `freshness` field on `GET /scans/{id}` with a green top banner for version updates (#883) and a
  reconnecting freshness state for a dead SSE push (#887); attempt number plus out-of-order protection on live
  SSE state (#895); the Assess "Processing details" panel (#922, PRD Phase 1 slice); a files column on the
  scan history table (#893). The ADR 0020 source cache was re-keyed by content checksum for cross-scan reuse
  (#928) and its dead read side wired up (#927); the scheduled Drive sweep now skips when nothing changed
  (#933); and Azure worker-replica visibility reached Discover with the write path admin-gated (#950).


### 2026-09-04 → 2026-09-07

- **Live Operations became an admin surface an operator can actually work from.** Run details open in
  a drawer (#1279) with one drawer shape and seven sections on every node (#1387); a visual real-time
  component view (#1340); topology stays visible while idle (#1311); crisp traffic edges (#1336);
  graph routing cleaned up (#1329); infrastructure and jobs separated (#1406); worker cards kept apart
  (#1399); connected workflows shown (#1448); completed stages stay connected (#1478).
- **Capacity and worker telemetry made truthful, in eight steps** (#1306 Azure worker capacity detail,
  #1404 the queue tile counts only slots that can claim the work, #1410 bounded gauges plus a
  stale-stream state and who can actually claim the queue, #1411 truthful per-replica capacity, #1420
  utilisation shown as *unavailable* without replica telemetry rather than as zero, #1423 replicas
  counted by replica identity, #1432 the worker instance telemetry lifecycle finished, #1652 a
  draining replica's running jobs counted as busy slots). Every one of these replaced a confidently
  wrong number with either a right one or an explicit "unknown".
- **Which replica is running which job** (#1560), the draining replica named on the drawer with
  rollouts no longer all called "mixed" (#1668), failed runs told apart from idle (#1572), workflow
  linkage truth (#1519), an immutable claim time and a worker id that names one worker (#1408), and
  the running-job drawer given the lease evidence it never had (#1412).
- **The drawer led with 1000 dead replica names and buried the work** (#1574) — the registry bug in
  #1590 surfacing as an unusable UI.
- Recovery controls and telemetry (#1482, #1486, #1494); AI provider health in the Monitor panel
  (#1449); Monitor recent-job row collisions fixed (#1649); five previously-untested Monitor paths
  covered (#1280); a crash without `ResizeObserver` prevented (#1318); the job poll loop stopped on
  App unmount (#1401); work kept visible without capacity telemetry (#1632).
- Presentation: opaque toasts (#1419), compact and distinct stage notifications (#1635), standardized
  heartbeat bar palettes (#1628), live sparklines on workflow cards (#1613), workflow state views
  polished (#1490), and layouts tightened (#1300).
- **A run tile read "200%" with its progress bar drawn out of the card and across the map** (#1713).
  Assess had completed two documents against a discover-expected total of one; the ratio was a true
  fact about stale counts, but a gauge past 100% is a fact about nothing and its unbounded value was
  handed straight to CSS as a width. `runProgress()` now returns a clamped `pct` used for **both** the
  label and the bar — one number, so the two cannot disagree again — and names the excess in words
  ("1 more completed than the 1 expected · expected total is stale") instead of drawing it. The tile
  itself is rendered in the test, not just the helper: a correct helper the tile stopped calling would
  leave the arithmetic green and the card overflowing.
- **A draining replica's running jobs are busy slots, not nothing** (#1713). The capacity gauge read
  "Idle — 0 of 20 slots (0%)" directly above "8 documents in flight", from the same heartbeats:
  `_replica_capacity` counted only `ready` and `busy`, and a worker draining after a deploy is
  neither — for up to **nine minutes** per rollout (`ACP_SHUTDOWN_DRAIN_SECONDS` is 540), real work on
  real slots contributed neither capacity nor utilisation and surfaced as `unattributed_running`. The
  intent was already in the code and defeated one layer up: `WorkerInstanceReporter.draining()` exists
  to hold the heartbeat open through the drain, and the reader discarded the rows anyway. A draining
  replica now contributes exactly the work it still holds and **none of its free slots** — it will
  never claim them. Production reading went from 20 slots / 0 busy / 8 unattributed to 28 / 8 / 0. A
  regression caught by re-reading the diff: `no_capacity_with_queue` was keyed on `worker_slots`,
  which meant "some replica can accept work" only while draining replicas counted zero — it is keyed
  on `healthy_replicas` now, or the alert would have gone silent during exactly the rollout window it
  exists for. Follow-on polish names it on the drawer ("1 draining, holding 8 jobs") and stops
  `mixed_revisions` firing on every deploy for the whole drain.
- **A cached permission denial outlived the permission grant** (#1713). `billing_block` held every
  answer for an hour, failures included, so the cost panel named a missing Cost Management Reader role
  for the rest of the hour after the role was granted — the observed remedy was restarting the
  revision. The long hold is right for a success (Cost Management rate-limits and the panel polls
  every 60s), and wrong for a failure, which is almost always something an operator is actively
  fixing; failures now hold 60s while successes keep the hour, and Azure's `Retry-After` still wins.




## Feature: Certification report as an audit artifact · #4698

Turned the per-scan certification PDF (`api/report.py`) from a scan summary into an audit artifact an
auditor can trust and reproduce. The backlog (docs/TODO.md P4) had drifted stale — most items had
already shipped and the file never said so — so this began by reconciling it against the code, then
built the genuine remainder. Every figure is a real, recomputable count or a ratio shown with its
basis; where a denominator is not tracked the number is omitted, not invented (ADR 0016).

- **Reconciled the stale P4 backlog against `report.py` · #4738** (#497). Struck the items already shipped —
  R1 evidence appendix, R2 decision block, R3 why-certifiable prose, R4 chain-of-custody digest, R6
  richer inventory, R7 score explanation, R-A scope-of-assertion, R-B audit-log excerpt — each with
  its rendering code named. Left R5/R9–R15/R-C–R-E open honestly rather than claim them done. The
  section had described the report as "a scan summary, not yet an audit artifact"; that was no longer
  true and the file was the last place saying so.
- **POUR — pass rate by WCAG principle · #4739** (#496). Groups evaluated criteria under Perceivable /
  Operable / Understandable / Robust (the SC's leading digit) and shows the pass rate per principle.
  Deterministic and honest by construction: the four principles partition the evaluated set exactly
  (a test pins `sum(evaluated) == the report's own evaluated count`), and it is a pass rate *among
  evaluated checks* — explicitly not a conformance percentage. Not-evaluated and review-only criteria
  are excluded; a principle with nothing evaluated shows "—", never a fabricated 0%.
- **Provenance — method, pipeline, reproduce, supersedes · #4740** (#498, R11/R12/R-D/R-E). A "how this
  result was produced" section carrying the scan's real counts (criteria evaluated, deterministic vs
  AI-assisted split, approvals, fixes re-validated), the pipeline in order, a **reproduce** line
  ("re-run against rubric hash `<h>` → same findings"), and a **supersedes** line naming the previous
  scan of the estate — the last two rendered only when their datum exists.
- **Human review & assurance — KPI + honest ratios · #4741** (#500, R9/R10). Review outcomes
  (reviewed / approved / rejected) counted from the immutable `decision_log`, deduped per
  (file, criterion) so they can never disagree with the sign-off shown elsewhere; a deterministic ÷
  evaluated assurance ratio; and effort as fixes-cleared ÷ findings *with that basis named*. The
  "cleared ÷ attempted" ratio is deliberately omitted — only re-scan-cleared fixes are recorded, so
  the attempted denominator is not tracked and inventing it would be dishonest.
- **Independent-verification steps + POUR bar chart · #4742** (#503, R13). Per document format actually in
  the scan, the mainstream tool and checks that let an auditor confirm the result themselves (Word /
  PowerPoint / Excel Accessibility Checker; Acrobat or NVDA/VoiceOver for PDF) — generic per format,
  never a claim about a specific document. Plus the POUR rates drawn as bars beside the table.
- **Auditor's guide to reading the report · #4743** (#504). New doc `docs/certification-report-for-auditors.md`
  — leads with the one thing not to misread (a score of 100 = "no blocking findings among the criteria
  evaluated", not "WCAG 2.1 AA conformant"), maps every section to what it does and does not let you
  conclude, and closes with three ways to trust it without trusting us (recompute the digest,
  reproduce the findings, verify a document by hand). Distinct from `conformance-report.md`, which is
  ACP's own platform-UI VPAT.

- **P-13 – P-20: the report honesty set** (#737, #739, #740, #742, #744, #748, #750, #752, #755, #756). A
  material-limitations notice (#737, #739), stable finding identifiers in the evidence appendix (#750),
  report provenance and freshness in the header band (#740, #742), per-finding status across seven named
  states (#748), report-level reconciliation checks with an integrity warning box (#744), richer evidence
  presentation carrying location / expected / confidence / timestamp / redaction (#752), ambiguous assurance
  language removed (#755), and print / PDF / AT behaviour — page headers, `repeatRows`, `KeepTogether` (#756).
- **The PDF itself became accessible and verifiable** (#767, #768, #689, #711, #665, #733, #722, #698). A
  Chromium HTML→PDF pipeline produces an accessible tagged report (#768) that passes `pdf.tagged` / WCAG
  1.3.1 (#767); a QR code and `/public/verify/{scan_id}` endpoint let a reader check a printed report against
  the live record (#689, with `ACP_PUBLIC_URL` documented for it — #711). Per-fix assurance tiers and a
  per-criterion compliance table (#665), assurance / confidence mode bars (#733), the AI reasoning basis
  (source + why_review) rendered for proposed fixes (#722), and reproduce instructions rewritten as an
  actionable 3-step table (#698).


- **The ACR workspace, Phases 1–4** (#1161, #1178, #1186, #1191, #1197). A WCAG 2.2 conformance report
  with an evidence-gated decision model. The standards catalog is **generated from the W3C
  Recommendation** rather than hand-transcribed — 55 criteria, 31 Level A and 24 Level AA — because a
  missing criterion or a wrong level stays invisible at every stage until a customer's procurement
  reviewer finds it; running the generator, rather than reading it, established that 4.1.1 Parsing is
  present in WCAG 2.2 but titled "(Obsolete and removed)" and stripped of its conformance-level marker.
  Phase 1 landed domain and persistence only, reachable from nothing, and said so (#1161). Phase 2
  added axe ingestion, the metadata editor and evidence gaps (#1178); Phase 3 guided manual test plans
  and the publish gate that consumes them (#1186); Phase 4 publication with immutable snapshots and
  revisions (#1191). Publication is the one irreversible act in the feature — an ACR goes into a
  customer's procurement file and cannot be recalled — so `POST /acr/{id}/publish` **assembles the
  existing gate rather than rewriting it**, calling the same `acr_validation.validate`,
  `acr_authz.may_publish` and `acr_freshness` the screens call. A second implementation of the gate is
  how a screen goes green while the real check is red. The check order is deliberate — already
  published, then whether the *caller* may publish, then readiness — and it goes through `acr_authz`,
  never `core.is_admin`. #1197 makes the export a PDF a screen-reader user can actually read.
- **A PDF/UA-1 conformance report, built before it was wired** (#1159, #1198, #1199, #1201, #1208). Built
  and validated via WeasyPrint and explicitly recorded as **NOT yet wired in** (#1159) rather than
  announced; then made portable and deployable (#1198), made to actually run in CI (#1199), served with
  a way back that needs no build (#1201), and the gate extended to the other pipeline and the test
  image (#1208).
- **Report arithmetic** (#1156, #1168). The report's "Files affected" column counts files, not findings
  (#1168), and an Assessment Run Integrity Gate was added with the manifest able to feed it (#1156).


- **"Can this deployment produce a tagged PDF?" — answerable without a credential** (#1211). The ACR's
  accessible export needs WeasyPrint, which binds to Pango, a **system** library a pip pin cannot supply. So
  *"`requirements.txt` pins weasyprint"* and *"this container can produce a tagged PDF"* are different claims,
  and only the first was checkable from outside; the endpoint answering the second requires an OAuth bearer,
  so an unauthenticated caller gets 401 whether the renderer works or not. On 2026-09-02 that gap cost a real
  investigation — confirming the renderer had reached production meant reproducing `redeploy.sh`'s base-image
  dependency hash by hand and matching it against a deploy log.
- **The review packet stopped telling reviewers nothing had shipped** (#1212, #1215). A packet built from
  `main` opened by describing the WeasyPrint renderer as a *proposal* with `scans.py` untouched — **every
  clause false since #1201**. The filenames said it too: `candidate.pdf` was the live renderer and
  `shipped.pdf` the one just retired. #1215 ships the reading order inside the packet, since NVDA cannot run
  in this environment and a reviewer needs the evidence rather than an instruction to go and verify it.
- **ADR 0034 Addendum 3 — the PAC attempt, including that its reason was untested** (#1219). Addendum 1 gave
  "not run — Windows only" for PAC 2024. The *fact* was true; the *reason* had never been checked, and an
  untested reason attached to a true fact reads as settled. So it was tested: PAC 24.4.4.0 downloaded and run
  under Wine 9.0, where it dies with a `TypeInitializationException` in mscorlib. The reason turns out to be
  nearly right for the wrong cause — which is the point of recording it.


### 2026-09-04 → 2026-09-07

- **All four VPAT editions now render, on catalogs derived from the standards themselves** — the
  largest single workstream in this window, delivered as Phase 6.1 → 6.4:
  - **6.1** the Revised Section 508 requirement catalog, derived from 36 CFR 1194 (#1539) — and the
    catalog guard that shipped with it and **guarded nothing** was then made to run (#1557).
  - **6.2** a matrix row says which standard it came from, and a 508 edition gets 508 rows (#1550).
  - **6.3** the Revised Section 508 Report renders, so the edition opens (#1555).
  - **6.4** the EN 301 549 catalog, committed empty behind a gate that reads it properly (#1570), the
    EU report rendering against a catalog that did not yet exist (#1582), and finally the catalog
    itself with all four editions (#1619).
- **A report could declare the Section 508 edition and contain no Section 508** (#1532). The edition
  label and the content were independent; a customer could have received a conformance report that
  named a standard it did not assess.
- **The EN generator said clause 9 has fifty-six; the catalog it writes has fifty-eight** (#1676) —
  a generator disagreeing with its own output, found by checking rather than by a customer.
- **The VPAT template's headings, as a catalog with provenance** (#1645), with the 508 chapters and EN
  clauses headed in the template's own wording (#1666) and the WCAG report laid out the way the ITI
  template lays it out (#1648). The criteria list groups Section 508 by chapter so a chapter can be
  marked in one decision (#1562).
- **The ACR as an accessible Word document, without the ITI template** (#1484), wired to a route
  behind its own accessibility gate (#1499), offered on the export tab with the gate visible before
  download (#1501), and the export finished — leaks stopped, then published (#1509). **A Word export
  nobody can open must fail the gate, not pass it silently** (#1558), and the export gate's findings
  rendered as the literal word "check" (#1510).
- Honesty about limits: the ACR PDF states inside itself what has not been validated about it (#1416),
  the limitations notice reaches the PDF people actually download (#1439), ACR export validation
  limits are shown in Conformance (#1430), and the acceptance table — which described a product two
  phases old — was corrected (#1470), given a command where it had a count (#1527), and row 13 closed
  because the structure is what it asks for (#1653).
- Exact model provenance added to conformance reports (#1644).


## Feature: Structural evidence renderers (Remediate preview) · #4699

Document-structure findings showed a generic "structure not extracted" note; these surface the real
extracted structure as review evidence, computed on demand via owner-scoped endpoints (the geometry
pattern) so they need no rule-path edit, DB migration or diff-pipeline change. docx-only and honest —
real extracted content, degrading to the generic note, never a fabricated tree.

- **Table-header association evidence · #4744** (#493) — the final tier-1 renderer. Parses the docx
  `<w:tbl>`/`<w:tr>`/`<w:tc>` and shows the real cell grid with the header row highlighted, stating
  plainly whether that row is *marked* as a header (`<w:tblHeader>`) or only reads as one — the exact
  association a screen reader needs, and what the 1.3.1 fix adds. Completes the set with reading-order
  (#490) and heading-outline (#492).

- **Trace environment + outcome tags on file traces** (#537, P1). Two Langfuse-logging fixes for a shared
  project. (1) Every trace is stamped with an ENVIRONMENT (production / staging / demo) — set on the SDK
  client from `ACP_ENV` / `LANGFUSE_TRACING_ENVIRONMENT`, defaulting to `production`, sanitised to
  Langfuse-safe chars so a stray value can't 400 every trace, and passed via try/except so an older SDK
  still constructs — so a shared project's traces separate instead of mingling under `default` (what the
  live traces showed). (2) File traces carry OUTCOME tags at assess time (`result:fail|needs-review|pass`,
  `pii:flagged`) so the native Langfuse list filters by result and PII, not only document + format; one
  authoritative `set_outcome_tags` update re-includes the base + rule-fail tags (Langfuse replaces a
  trace's tags). Categories/counts only, never a value — the PHI guard holds. `api/lf.py` + `api/handlers.py`,
  not RULE_PATHS; 176 langfuse/assess tests green, redaction guards green.


## Feature: ACP Managed Content Workspace (ADR 0044) · needs a Feature

Upload-first document intake: the customer brings documents to ACP instead of connecting a source.
Built data-model-first, with each PR landing behind no caller until the layer beneath it was real.

- **The store, built as a data model before a route** (#1001, #1003, #1008, #1010, #1017, #1019, #1023,
  #1024, #1119). The Managed Content Workspace data model (#1001) with `content_workspace_documents`
  and `versions` tables plus CRUD (#1003); `api/workspace_blob.py` as the Blob store (#1008); the
  upload-session and completion endpoints (#1010); a document-scoped upload session for new versions
  (#1024); a download-original endpoint (#1017); a baseline retention sweep for versions (#1019, PRD
  §28); and a per-workspace storage quota (#1023, PRD §9). #1119 reserves the version row at session
  time rather than at completion — so a crashed upload leaves a row that can be reconciled instead of
  leaving nothing at all.
- **Uploads are treated as hostile input** (#1013, #1015). An extension allow-list plus **magic-byte
  quarantine** (#1013, PRD §13) — a platform whose entire purpose is ingesting untrusted documents
  cannot trust a file extension — and duplicate detection and resolution (#1015, PRD §12).
- **Connected to the real scan engine, then made enumerable** (#1116, #1118). #1116 connected one stored
  version to the existing scan/assess engine — a per-version assess endpoint and a `workspace_scan_file`
  job. #1118 is the enumeration half: `POST /content-workspaces/{id}/assess` creates the run and **one**
  `workspace_scan_discover` job that lists the workspace and fans out one job per document, so a
  customer uploads a folder and gets one run with one total and one completion rather than N per-version
  scans to correlate. Enumeration lives in the worker, not the route, and that is the design claim: the
  population is re-derived from the authoritative table on every attempt, so a document uploaded between
  pressing Assess and a worker claiming the job is included, and a reclaimed job resumes correctly.

## Feature: Durable orchestration and worker reliability · needs a Feature

The durable job queue existed; this window made it correct under the failures it was built for — a
worker dying mid-job, two attempts racing, a cancellation nobody honoured.

- **A result can only be written by the attempt that produced it** (#1068, #1075, #1080, #1110, #1112,
  #1115, #1117). Result writes are fenced to the job attempt that produced them (#1117); only the
  current holder may renew a lease, and an unsupported claim is withdrawn from the map (#1075); only
  the current claim may publish an outcome, not merely renew (#1080). A terminal row plus a
  cancellation request **does not prove the work stopped** (#1115), so the interruption the reclaim
  records is now rendered (#1112), a worker that died holding a job says so instead of nothing at all
  (#1110), and which job and which document it had open is recorded (#1068).
- **Cancellation that actually reaches the work** (#1051, #1061, #1079, #1081, #1101). `check_cancel()`
  plumbed through to the threads doing the work (#1079); discovery given real cancellation checkpoints,
  with **five paths that had been swallowing them** fixed (#1081); superseding a scan now stops the
  worker already running it (#1061). A rejected scan submission no longer destroys the run it would
  have replaced (#1051, H-03), and a job someone STOPPED is no longer reported as a job that FAILED
  (#1101).
- **Failures stopped being silent** (#1055, #1086, #1104, #1108, #1111, #1113). Every silently-swallowed
  failure in `api/` was given a voice (#1108). A folder ACP could not read is not a folder with nothing
  in it (#1104) — the same class of lie as #1195 for images. A folder is counted once however many
  times its job runs (#1111); active discovery is separated from previous inventory and counts (#1113);
  and an overload 503 no longer claims "No changes were made" on requests that **may have written**
  (#1055).
- **Database and connection behaviour under real load** (#1040, #1045, #1084, #1109). The API replica's
  DB pool no longer collapses to 10 connections when `ACP_WORKERS=0` (#1045); the schema is verified at
  boot instead of replayed, **so replicas stop deadlocking** (#1084); concurrent Discovery HTTP request
  transports are isolated (#1109). #1040 added the `orchestration_events` and `worker_instances` tables
  as PR 1 of 5 with no caller — the same no-caller-first discipline ADR 0042 used.
- **Verification fails closed** (#1072, #1082). A re-scan that could not run never grants credit (#1082),
  and a stopped run outranks a healthy service light — a heartbeat is no longer read as progress
  (#1072).


- **The durable scan path, hardened 2026-08-27** (#889, #894, #896, #897, #900). The built reconciliation
  sweeper was wired into production (#889) — it existed and was not running; `scan_to_job` mapping is written
  on the durable `scan_discover` path (#894); `complete_job` / `mark_job_cancelled` / `fail_job` are guarded
  against a zombie-worker race (#896); scan status flips to `discovered` **only after every durable write
  lands** (#900); and `disposition_audit` ids were made deterministic, closing the PRD §20 idempotency gap
  (#897).

## Feature: Media captions — 1.2.1 / 1.2.2 · needs a Feature

- **Audio and video became assessable, in four slices** (#1158, #1166, #1177, #1185). A local
  media-to-captions pipeline behind a probed optional engine (#1158); standalone audio and video
  assessed against 1.2.1/1.2.2 (#1166); a 1.2.2 finding arriving with a caption file a reviewer can
  approve (#1177); and a caption file a reviewer can correct **and can actually obtain** (#1185). The
  engine is probed rather than assumed, so a deployment without it degrades to "not assessed" instead
  of to a false pass — which is the whole reason the lane can be shipped optional.


- **Slice 5: a caption a reviewer can correct while watching the media** (#1221) — the correction loop closed
  against playback, so a reviewer is not editing a transcript blind.

## Feature: ACP — Iteration 11 delivery · #5478

Bound to ADO Feature **#5478** (Epic #3664), created 2026-09-04 with sixteen Tasks covering Iteration 11
(2026-08-24 → 2026-09-04). Hours on the ADO Tasks are **delivery estimates, not measured elapsed time**.
  The roll-up as supplied listed per-item hours summing to 85 against a stated total of 80; on
  2026-09-04 the largest item (#5487) was reduced 8h → 3h to reconcile them, bringing the Feature to 80h.
Each bullet below names its ADO Task id and the PRs behind it, so the board and this log can be reconciled
in either direction.

- **Simplify Overview and Discovery information flow** (Task #5479, 5h) — #1217, #1223, #1226, #1227, #1234,
  #1236, #1237, #1261. Redundant estate/context panels removed, scan summaries consolidated, scope
  information repositioned, and "Scope of This Assertion" standardised.
- **Inventory snapshot exports made reachable** (#1220, #1225, #1265). The Export CSV/JSON controls were
  moved to the top of the inventory snapshot section (#1220, refined in #1265) and the Discover scan
  summary and its exports improved (#1225) — folded under Task #5479, whose scope this shares.
- **Restore rich Discovery live-progress experience** (Task #5480, 6h) — #1229, #1230, #1231, #1233, #1249,
  #1267, #1268. The detailed SSE checklist and lifecycle summaries restored, completion state persisted
  across refresh, and recovery messaging added for incomplete or suspicious scans — #1267 blocks a
  suspicious Discovery scope collapse outright rather than reporting it afterwards.
- **Build authoritative live Assessment card** (Task #5481, 7h) — #1235, #1241, #1242, #1244, #1245, #1251.
  Live preparation and processing stages, document counts reconciled, file-level activity retained, and
  progress restored after navigation.
- **Improve Assessment worker and throughput visibility** (Task #5482, 4h) — #1232, #1239, #1252.
  Active/standby worker detail, queue status, capacity and throughput, with expandable processing details;
  #1232 sets a *reviewed* production capacity baseline rather than an assumed one.
- **Build detailed Automated Remediation live card** (Task #5483, 7h) — #1238, #1244, #1245. SSE-driven
  remediation stages, document and WCAG-rule activity, fix progress, verification status and corrected-copy
  tracking, replacing the completed Assessment card while remediation runs.
- **Simplify the Remediation review experience** (Task #5484, 5h) — #1243 plus the review-surface work in
  #1249. Redundant previews and whitespace removed while approval/rejection actions and efficient approval
  across related findings were preserved.
- **Implement Release publishing workflow** (Task #5485, 6h) — timestamped Remediated output folders, source
  folder structure preserved, corrected-file publishing prepared, and remediation provenance recorded in
  document metadata. *Recorded from the sprint roll-up; the individual PRs for this task were not separable
  from the Remediate wave above by commit subject alone, so no PR list is claimed here.*
- **Add tenant-fair worker scheduling and capacity controls** (Task #5486, 6h) — #1232, #1239, #1259.
  Durable tenant-fair scheduling with Postgres fair-claim row locking, so **one user can no longer monopolise
  the worker pool** — the multi-tenant failure the durable queue made possible and did not yet prevent.
- **Create the Admin Live Operations ReactFlow view** (Task #5487, 3h) — #1254, #1255, #1256, #1257, #1263.
  An admin-only Live Operations tab with live Azure traffic flow, worker nodes, shared-queue status,
  utilisation, recent runs kept visible, and clickable run detail.
- **Add accessible Live Operations notifications and trends** (Task #5488, 3h) — #1269, #1272. Toast contrast
  improved and trend/sparkline interactions made keyboard accessible — the new admin surface held to the same
  bar the product asserts for customers.
- **Add source-level run history and activity clarity** (Task #5489, 4h) — #1257, #1270, #1271. Run-history
  placement and labels improved, loading states announced, and source-specific discovery history clarified.
- **Extend the WCAG palette toggle across the application** (Task #5490, 6h) — #1222, #1224, #1247, #1250,
  #1262, #1266, #1273, #1274, #1275, #1277. Hard-coded colours replaced with semantic tokens over four phases,
  WCAG
  mode extended beyond the nav tabs to every workflow tab, and FastPass regression coverage expanded with it.
  #1277 adds the non-text contrast overrides for the active dot and the rule-breakdown bars — the two
  components the token migration had left below the 3:1 threshold.
- **Create unified Google and Microsoft user onboarding** (Task #5491, 5h) — #1240. Google tester
  whitelisting guidance, Microsoft Entra guest invitations, provider-specific onboarding states, and Settings
  narrowed to Owners and Users.
- **Integrate governed Hugging Face vision support** (Task #5492, 5h) — #1246, #1258, #1260. The Inference
  Endpoint adapter added under the governed activation path, provider behaviour hardened with a
  **deterministic readiness probe**, fallback preserved, model provenance recorded — and #1258 renamed a
  fallback test whose name misdescribed what it asserted.
- **Add secure file-level Langfuse observability** (Task #5493, 4h) — #1202, #1253. File-level scan,
  assessment and remediation traces carrying outcome, model usage, cost and reproducibility data, with trace
  access isolated by account through privacy-safe owner identifiers.
- **Production reliability, CI, merge and deployment hardening** (Task #5494, 4h) — #1253 is the substantive
  one: a 2026-09-02 audit found **three routes missing ownership checks**. `GET /inventory` served
  cross-account file listings because the global path-dedup table has no owner column (now admin-only, with
  regular callers directed to `GET /scans/{sid}/inventory`); `GET /scans/jobs/{job_id}` let any authenticated
  caller who knew or guessed a job id read another user's scan state — source paths, phase, file counts; and
  the remediate POST was likewise unscoped. Same class as #1202 and #872, found by looking rather than waiting.

## Feature: Canonical stage model and durable workflow execution · needs a Feature

The window's deepest architectural change: a single canonical account of what stage a piece of work is
in, owned by the server, durable across deploys, and the same everywhere it is displayed. Before this,
each surface derived stage from whatever events it had seen. Distinct from *Durable orchestration and
worker reliability* above, which is the job-queue layer (leases, cancellation, connection budgets); this
is the layer above it — what stage the *work* is in, independent of which attempt is executing it.

- **Scan stages bound to a durable workflow execution** (#1485), with each stage **single-flight**
  (#1489), completion recorded **exactly once** (#1477), cross-stage execution **idempotent and
  transparent** (#1639), and stage transitions guarded (#1622). A failed stage execution re-runs; a
  finished one still does not (#1400).
- **Canonical stages made primary across the product** (#1697, #1661, #1663), with domain equations
  (#1698), domain accounting (#1700), intuitive counts (#1688) and terminal labels (#1696), lineage
  integrity made explicit (#1701), and — the load-bearing one — **canonical stages kept truthful
  through deployments** (#1693).
- **Sealed manifests wired through runtime stages** (#1677), the canonical stage outbox run in the
  worker tier (#1681), and historical stage backfill run **once per fleet** (#1683) rather than once
  per replica.
- Durable stage cards own workflow status (#1614, #1515, #1563); stage history shown in Live Operations
  (#1528); reused stage executions explained in the UI (#1593); failed and stalled stages persisted
  (#1480).
- **Workflow identity across replacement and interruption**: downstream stages locked to immutable
  snapshots (#1383), workflow revisions named in scan history (#1507) and shown across the live UI
  (#1502), active work linked to its previous revision (#1508), replacement scans kept in one lineage
  (#1497), active workflows resumed after sign-in (#1415), an in-flight run rejoined after signing
  back in within a blob transport budget (#1364), and active workflow cards refreshed on tab focus
  (#1640).
- **Cumulative workflow stage cards** (#1719) — a stage stack that shows the run's stages
  accumulating rather than only the current one, so an operator can see the shape of a run in progress
  instead of a single label.



## Feature: Realtime operations event backbone · needs a Feature

A second event transport built entirely **default-off and shadowed**, proven against staging under
load, and gated before any traffic depends on it. Worth its own Feature because none of it is visible
to a customer yet and all of it is prerequisite to retiring the current polling path.

- **Shared realtime operations event contract defined** (#1546), then implemented as default-off
  canonical publishers (#1551, #1584), a default-off gateway (#1578), a browser shadow bridge (#1587),
  shadow diagnostics (#1548) and an isolated shadow harness (#1549) — with activation gated to staging
  (#1611).
- **Proven under load before promotion**: a repeatable multi-tenant load and chaos gate (#1569), a
  canonical realtime load and isolation gate (#1610), per-event staging latency measurement (#1685)
  with cold and warm gate latency split apart (#1694), batched Redis writes (#1686) observed in the
  staging gate (#1690), single-write transports preserved (#1691), the shadow publisher's Redis
  connection warmed (#1702), and a guaranteed warm soak wave (#1703).
- **A GO/NO-GO gate runs after every staging deploy** (#1679), through the ACA PTY (#1682). The
  discipline here is the point: the replacement transport cannot be switched on by opinion.
- **The load gate is decided on structure in CI and on the clock only in staging** (#1706). A
  wall-clock latency assertion on shared CI runners fails for reasons that have nothing to do with the
  code; the gate now checks in CI what CI can actually answer.



## Open items (backlog candidates)

- **The `acp` working copy is parked on a stale branch, and that made the delivery log look current
  when it was 307 commits behind.** `acp/` has HEAD on `worktree-feat-reconnecting-freshness`
  (`cbb6687f`, 2026-08-27) while the work landed on `origin/main` (`503f1916`, 2026-09-02).
  `ado-sync.sh delta` compares against HEAD, so it reported `mode=clean` with an empty delta — the
  standup would have skipped ACP entirely. The helper's existing guard covers "git failed and said
  nothing"; it does not cover "HEAD is not where the work is". Either the checkout should be returned
  to `main`, or `delta` should compare against the tracking branch. Until one of those happens, every
  future standup on this repo is one stale checkout away from silently reporting nothing.
- **Three Features in this window have no ADO id** — ACP Managed Content Workspace (ADR 0044), Durable
  orchestration and worker reliability, and Media captions (1.2.1 / 1.2.2). They are substantial enough
  to be Features rather than Tasks under an existing one, and are marked "needs a Feature" until ids
  are created under Epic #3664.
- **The PDF/UA-1 report is built, gated in CI and served, but its wiring status should be confirmed
  before it is described to a customer.** #1159 landed it explicitly NOT wired in; #1198–#1208 made it
  portable, deployable, CI-gated and served. Whether it is reachable in the product for an end user is
  the one claim in this window not verifiable from commit subjects alone.

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

- **Uncommitted in the working tree as of 2026-08-29** — `frontend/src/assessSummary.test.jsx` is modified
  and unstaged, and the repo root carries a large set of untracked binary deliverables (the
  `ACP-Azure-Deployment-Architecture`, `ACP-Discover-Redesign`, `ACP-Discovery-Redesign-Why`,
  `ACP-Location-Golden-Record` and `ACP-MovaIO-Prod-vs-Staging` PNG/PPTX sets, `ACP_DOCX_WCAG_Fixtures`,
  `docs/Archive.zip`, `AGENTS.md`, `deploy/compose/docker-compose.override.yml`). None of this is on a
  branch. `AGENTS.md` and the compose override are the two that look like they belong in the repo and are
  not in it; the decks and fixture archives probably belong somewhere other than the repo root. Needs a
  decision, not a commit-everything sweep.
- **Two open PRs look superseded and should be closed or reduced** — #787 and #790 appear to duplicate work
  already merged (#774 for the 1.3.5 detectors, #777 for Power BI DirectQuery). Not verified line by line;
  flagged for a comparison pass rather than asserted as dead.

---

- **`acp-redesign-review-queue` is a git *worktree* of `acp`, and the standup nearly counted its
  history twice.** Its `.git` is a file, not a directory, so `find -maxdepth 3 -name .git -type d`
  — the discovery command in the `ado-standup` skill — **does not find it at all**; it was only
  reached because it has a delivery log. It then reported `mode=no-prior-sync` with **573 commits**,
  of which exactly **one** (`143bbf3f`, "Redesign lifecycle disposition review queue") is not on
  `origin/main`; the other 572 are `acp`'s own trunk. Its sync was deliberately **not** marked, because
  a marker there would promise coverage in a log file that checkout does not contain. Two decisions
  needed: whether the skill's discovery should drop `-type d`, and whether worktrees should be
  excluded from the standup entirely and folded into their source repo. The same shape applies to
  `acp-utsw` (a worktree of `acp-utsw-source`), which is currently harmless only because both are clean.
- **An uncommitted change in the working tree strips `frontend/src/assessSummary.test.jsx` down to a
  stub — 23 insertions against 356 deletions.** It removes the file's stated purpose header (the four
  things the summary panel must never do: render zeros for a run that has not happened, say "No
  findings" without the coverage caveat, print a percentage or an estimate of human effort, print a
  partition that does not add up) along with the fixtures and most of the assertions, leaving a
  single-criterion happy path. Nothing about it looks like a deliberate simplification, and it is not
  on any branch. Whoever left it there should either finish it or discard it before it is committed by
  a session that assumes it is intentional — a stripped test suite still passes, which is exactly why
  this would not be caught later.

- **PR #1713 squashed five unrelated fixes into one commit spanning four Features.** A cached billing
  denial, CI concurrency on `main`, draining-replica capacity accounting, the Live Ops drawer, and the
  run-tile progress clamp arrived as a single squash. Each is well-described and each was bite-checked,
  but the PR number now appears under Continuous deployment, Scan-run experience and Certification
  report at once, so neither the board nor this log can tell from the id which change is meant. Worth a
  convention call: one PR per Feature-sized change, or a commit trailer naming the Features it touches.


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
- **2026-08-20 (certification report as an audit artifact)** — Two new Features. To **Certification report
  as an audit artifact**: the P4 backlog reconcile (#497) and the genuine remainder — POUR by principle
  (#496), provenance/reproduce/supersedes (#498), human-review KPI + honest ratios (#500),
  independent-verification steps + POUR bar (#503), and the auditor's guide doc (#504). To **Structural
  evidence renderers**: the table-header association renderer (#493), completing the tier-1 set with #490/#492.
  All report.py / store.py / doc_structure.py / docs — no rule-path files, no other session's surfaces. One
  overnight autonomous session, each PR merged green. (The frontend CI briefly went red on a date time-bomb in
  `wizardScopeCoverage.test.jsx` at the Aug 19→20 rollover; another session's #505 fixed it first, so this
  session's duplicate fix was dropped.) **Sync marker deliberately NOT advanced** (same convention).
- **2026-08-20 (Langfuse polish + assess redesign + scan safety net)** — Six PRs merged today. To
  **Observability — AI tracing and cost (Langfuse)**: #506 (operator email out of every trace NAME + legible
  verdict names + `format:` tag) and #507 (cross-scan "this document over time" history). To **Estate
  coverage (#4597)**: #471 (redesign Phase 0 — explicit units + one source of truth for the estate numbers)
  and #488 (Phase 2 — decision-first KPI cards + drop the duplicate pass-rate). To **Remediate review queue
  (#4598)**: #469 (Phase 1 — the Auto-remediate card folded into the status hero, one CTA). To **Scan-run
  experience (Track A)**: #513 (per-file wall-clock safety net so one stuck document can't stall a run —
  diagnosed live from the Langfuse traces during a real prod SharePoint assess that was cold-start slow, not
  hung). Test hygiene #505 (the wizard date time-bomb) was already recorded by the entry above and is not
  re-logged as a Task. **Sync marker still NOT advanced** (`fad0dfbe`, same convention as the prior entries):
  the large delta since it remains other sessions' undocumented feature work, left for them to characterise.
- **2026-08-20 (collapsed-scan probe fixes)** — To **Continuous deployment to Azure (#4614)**: the two halves
  of the `newest scan is full-size` probe failure caught on prod — the selector hardening (#520, default to
  the newest non-collapsed scan) and the source fail-closed (#522, require an explicit scan source so `local`
  is no longer a silent default). The scheduled-sweep fallback was already fixed; these close the selector and
  on-demand doors. Investigation-led: verified the sweep bug was already closed and ran a caller audit before
  changing the API contract. **Sync marker still NOT advanced** (same convention).
- **2026-08-20 (scan-wizard/picker hardening + estate retention + trace polish + dead-code prune)** — Added
  the day's remaining undocumented work, mapped to four existing Features. To **Scan-run experience (Track A)**:
  the folder-picker honesty pass (#512), recoverable/classified folder-load failures (#511), scope-correctness
  fixes (#501 composite id + #502 empty-folders), and the wizard step-1 declutter + format-population labelling
  (#509 + #514). The collapsed-scan probe fixes (#520/#522) are logged separately by the entry above (#531),
  under #4614 — not re-logged here. To **Estate coverage (#4597)**: the whole-estate "last modified"
  age/retention distribution (#515 backend + #517 frontend). To **Observability — Langfuse**: live per-file
  assess scores + file-level severity (#518) and the dead scan/assess-trace-function prune (#524 — this
  session's own work, seven orphaned functions removed, −133 lines, zero live callers re-verified). To
  **Documentation**: ADR 0038 pausable/resumable scans (#495), the pilot-deck technical contract (#519), and
  the GPU/vision production-contract answers (#521). Already-logged work (#506/#507/#513/#504/#505 and the
  report/structural set) was not re-logged. **Sync marker still NOT advanced** (`fad0dfbe`, same convention):
  the delta still contains other sessions' undocumented Aug-19 feature work, and #526 (ADR 0039 regional
  resilience) + #527 (Open-in-Langfuse link) landed mid-write — both other sessions', left for their owners.
- **2026-08-20 (Discover scope-only + CI-cancel fix)** — To **Discover & Assess lifecycle rules (#4618)**:
  #532 — Discover's wizard is now scope-only (which source / which folders); scan profiles, format cards and
  the criterion × format matrix moved to Assess (PRD DISC-01 phase-1 exit). To **Continuous deployment
  (#4614)**: #525 — scoped CI cancel-in-progress so `main` runs finish and fire their `workflow_run` deploy,
  instead of a newer commit cancelling a run and silently skipping the ship. **Sync marker deliberately NOT
  advanced** (same convention as the prior entries).
- **2026-08-20 (multi-admin + in-app admin management)** — From a user report that a teammate saw different
  privileges. Root cause: single-owner admin model (`ACP_OWNER_EMAIL` only). To **Multi-tenancy and the
  control plane (#4608)**: #534 — `ACP_ADMIN_EMAILS` + `core.is_admin` as the one gate both the SPA flag and
  the API enforce (no-op until configured); #535 — in-app owner-managed admin promotion from Settings →
  Users (store-backed set, `is_owner` root-of-trust, owner-only `PUT /admin/admins`, three-tier badges +
  toggle). Both green, tested (9 + 10 cases), not RULE_PATHS; ship on the next approved prod deploy. **Sync
  marker deliberately NOT advanced** (same convention as the prior entries).
- **2026-08-20 (trace env + outcome tags)** — To **Observability — AI tracing and cost (#4697)**: #537 —
  stamp each trace with its ENVIRONMENT (so a shared Langfuse project's prod/staging/demo traces separate
  instead of mingling under `default`) and tag file traces with the assess OUTCOME (`result:*`, `pii:flagged`)
  so the native list filters by result and PII. PHI guard intact (categories/counts only). Not RULE_PATHS.
  #538 (ADO Feature-ID binding) is itself a delivery-log edit, so no entry. **Sync marker deliberately NOT
  advanced** (same convention as the prior entries).
- **2026-08-20/21 (the big overnight batch — redesign build-out, live assessment, R20/R4)** — brought the log
  current for ~50 merges since #542 (the docs/ADO session that binds IDs had gone; no other session was
  logging the new work). To **Remediate review queue (#4598)**: the R1–R12 redesign core built as standalone
  modules by the claude[bot] pipeline (R2/R3/R5/R9 #551, R6/R8/R10 #559, R11/R12 #558, R4/R7 #560) then
  wired + all ten components mounted; **#569 R20 CSV** (mine); **#570 R4 removal** (the dropped stepper that
  shipped live — I filed/evidenced #568, acp-bf built the revert; I stood down on my parallel attempt to
  avoid a duplicate PR). To **Scan-run experience / Track A (#4696)**: the Live Assessment running screen
  (#553/#555/#556/#557/#561/#563/#566/#567). To **Estate coverage (#4597)**: the Assess results redesign
  (#545) and the Overview reconciliation/four-tiles/NEXT board. To **Discover & Assess lifecycle (#4618)**:
  the lifecycle-rules step, discovery-results + dated exportable inventory (#562), disposition rule preview.
  To **Continuous deployment (#4614)**: #547 vision/GPU readiness on /readyz, and CI empty-merge/red-announce
  fixes. Policy items R22/R23/R24 settled (not built) per Jeremy. **Sync marker deliberately NOT advanced**
  (same convention): most of this is the bot pipeline's + other sessions' work, logged here for intake, not
  claimed.
- **2026-08-21 (Remediation redesign — R18, R19, R16)** — Added two shipped slices to **Remediate review
  queue (#4598)**: **R18 comments on a finding** (#573) and **R19 due dates on a document** (#586), both built
  as self-contained components mounted through the existing `renderDetailExtra` render-prop so the hot inbox
  the claude[bot] pipeline is actively rewriting stayed untouched — the collision-avoidance strategy the whole
  redesign push has used. R18 adds a new `finding_comments` table + owner-scoped routes; R19 reuses the
  R17 assignee decision axis with a new `kind='due_date'` (no new persistence). Also recorded that **R16
  fix-critical-first was already shipped** (the inbox's default `priority` sort is severity-first) and so was
  not rebuilt. Remaining R-series item: **R15 undo-a-batch** (touches the apply flow; feasibility being scoped).
  Per the new working agreement (#583) CI was not polled — merges gated on a single delayed check per PR.
  **Sync marker deliberately NOT advanced** (same convention).

- **2026-08-29 (standup sweep — the whole 273-commit delta, and the marker finally advanced)** — mode
  `clean`, prev head `6fa4f369` (2026-08-21), now `cbb6687f` (2026-08-27). **273 commits across seven days**
  (23 on 08-21, 26 on 08-22, 12 on 08-23, 86 on 08-24, 70 on 08-25, 39 on 08-26, 17 on 08-27), roughly
  PR #603 → #886. Tasks appended to fourteen Features: **Scan-run experience (#4696)** took the ADR 0004
  durable-queue build-out, single-flight scans, SSE progress and the preflight; **Estate coverage (#4597)**
  took the "0 documents" failure family, the 6× parallel BFS, the results dashboards and the estate-analytics
  rebuild; **Discover & Assess lifecycle rules (#4618)** took the rule-authoring completion plus the
  per-tenant and audit-attribution defects; **Certification report (#4698)** took P-13–P-20 and the tagged
  accessible PDF with QR verification; **Capability registry (#4612)** took six detector additions/upgrades
  and the full remediation-lane declaration sweep; **Continuous deployment (#4614)**, **Multi-tenancy
  (#4608)**, **PHI privacy (#4613)**, **Remediate review queue (#4598)**, **Test corpus and CI (#4605)**,
  **Assessment correctness (#4607)**, **Observability — Langfuse (#4697)**, **Dependency security (#4603)**
  and **Documentation** took the remainder.
  **The sync marker IS advanced this time**, breaking the convention the eight preceding entries used. Those
  entries deliberately held the marker back because each documented only a slice and left other sessions'
  work in the delta. This entry documents the delta in full, so holding the marker would only mean the next
  standup re-reads 273 already-written commits. Much of this work is the claude[bot] pipeline's and other
  sessions'; it is logged here for ADO intake, not claimed as one person's.
  Two things this entry does **not** do: it does not re-verify the individual PR claims against the source
  (the volume made that impractical, and the bullets follow the commit subjects and PR titles), and it does
  not resolve the untracked working-tree material recorded as a new Open item.
- **2026-09-02 (standup)** — Rollup sweep across all projects. ACP had **307 commits on
  `origin/main` undocumented** since the `cbb6687f` marker (2026-08-27 → 2026-09-02, 189 of them inside
  the 3-day window). Mode reported `clean` with an *empty* delta because the `acp/` checkout sits on
  `worktree-feat-reconnecting-freshness`, not `main`; the delta was recomputed against `origin/main`
  and cross-referenced against every PR number already named in this file, so the 222 lines of
  uncommitted log content already in the working tree from a previous session are not duplicated.
  Appended ~30 grouped Tasks across SharePoint source, Operator scan scope, v2 redesign, Alt-text,
  Test corpus and CI, Remediation, Assessment correctness, Documentation, Capability registry,
  Continuous deployment, Remediate review queue, Estate coverage, Lifecycle rules, Observability,
  Scan-run experience and Certification report. Three new Features written with no ADO id: ACP Managed
  Content Workspace (ADR 0044), Durable orchestration and worker reliability, and Media captions
  (1.2.1 / 1.2.2). Three Open items recorded, led by the stale-checkout blindness that hid this delta.
  Sync marker advanced from `cbb6687f` to `origin/main` head at the time of writing.
- **2026-09-04 (standup follow-up)** — Closed the gap the 2026-09-02 entry left open. `origin/main` had
  reached `369f0c6e` (#1275); 371 commits stood past the `cbb6687f` marker, of which 273 were already
  documented and **97 were not**. Two distinct groups, both now written up: a residue of ~33 small PRs from
  2026-08-27/29 (#883–#950, #1097) that fell between the grouped bullets of the previous pass, and 64 new
  commits from 2026-09-02/04. The new work is bound to ADO Feature **#5478** — *ACP — Iteration 11 delivery*,
  created this day under Epic #3664 with sixteen Closed Tasks (#5479–#5494) totalling 85 hours of delivery
  estimate. Its section names each Task id against the PRs behind it so the board and this log reconcile in
  both directions. One task (#5485, Release publishing workflow) is recorded **without** a PR list, because
  its commits were not separable from the Remediate wave by subject alone; that is stated in place rather
  than papered over. The `acp` checkout remains parked on `worktree-feat-reconnecting-freshness` — see the
  first Open item; the delta was again computed against `origin/main` and cross-referenced by PR number.

- **2026-09-07 (standup)** — Rollup across all projects. ACP was the only repo with new work:
  **416 commits on `origin/main`** past the `50bf1731` marker (2026-09-04 → 2026-09-07, PRs
  #1276–#1706), all of them undocumented. Mode reported `clean` and, unlike the two previous entries,
  the delta was **not** empty — the tip-resolution fix landed in `ado-sync.sh` on 2026-09-04 now
  compares against `origin/main` rather than the parked `worktree-feat-reconnecting-freshness` HEAD,
  so the stale-checkout blindness recorded as the first Open item no longer hides this repo's work.
  That Open item stands only for the checkout itself, which is still parked.
  Bullets were appended under twenty existing Features plus the Documentation section, and **two new
  Features written with no ADO id**: *Canonical stage model and durable workflow execution* and *Realtime operations event
  backbone*. Both are large enough to be Features rather than Tasks — together they account for
  roughly 90 of the 416 commits — and both are marked "needs a Feature" pending ids under Epic #3664.
  Three things this entry does **not** do. It does not re-verify individual PR claims against the
  source; at 416 commits over three days that was not practical, and the bullets follow commit
  subjects and PR titles. It does not open an "Iteration 12 delivery" Feature to mirror #5478, because
  no such ADO Feature exists yet and inventing an id is worse than leaving the work under its
  functional Features. And it does not mark `acp-redesign-review-queue`'s sync — see the new Open item.
  Much of this work is the claude[bot] pipeline's and other sessions'; it is logged here for ADO
  intake, not claimed as one person's.
  `origin/main` **moved while this entry was being written** — from `26ace4af` (#1704) to `03b85970`
  (#1706), two commits from a concurrent session. Both were picked up rather than left for the next
  run: #1705 under Local model benchmarking, #1706 under the new Realtime operations event backbone.
  The count above is therefore 416, not the 414 the first delta reported. Sync marker advanced from
  `50bf1731` to `origin/main` head (`03b85970`).

- **2026-09-07 (standup, second run of the day)** — The earlier run today (marker `03b85970`, PR #1706)
  covered 416 commits; **15 more landed in the hours since**, PRs #1707–#1724, all documented here.
  Mode `clean`, delta exact. This entry appends to nine existing Features rather than opening any new
  one — the work is continuation, not new territory: Assessment correctness (four bullets, led by pptx
  1.4.5 finally clearing and a regression no longer certifying a document), Local model benchmarking
  (the first measured Claude run on the adversarial set — 192 billed calls, $0.81, zero regressions
  introduced), Documentation (two stale-prose corrections, one of which was reaching customers in every
  draft ACR preview), Continuous deployment (the pending-CI-run cancellation that stopped main's middle
  commits shipping), Scan-run experience (three Live Operations gauge fixes), Release Center, Canonical
  stage model, and v2 frontend redesign.
  Two things this entry does **not** do. It does not re-verify PR claims against the source — the
  bullets follow commit subjects and bodies, which for this batch are unusually detailed and carry
  their own measurements. And it still does not open an "Iteration 12 delivery" Feature to mirror
  #5478: no such ADO Feature exists, and inventing an id is worse than leaving the work under its
  functional Features. Every Feature id cited here was already bound; **no new Feature was created**.
  `origin/main` was re-checked immediately before marking and had not moved. Sync marker advanced from
  `03b85970` to `8c854d71` (#1724). Much of this work is the claude[bot] pipeline's and other
  sessions'; it is logged for ADO intake, not claimed as one person's.
