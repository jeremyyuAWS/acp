# ACP — Delivery Log

Work on the Accessibility Compliance Platform. Grouped for Azure DevOps intake:
each top-level heading maps to a Feature, each bullet to a Task.

Repository: `jeremyyuAWS/acp` · 1,771 files · 1,067 commits total
**This log starts at 2026-08-01.** The project predates it by ~1,000 commits; earlier work
is not covered here. The `(#NNN)` references are GitHub PRs, not ADO work items.

---

## Feature: SharePoint as a document source

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

## Feature: Operator scan scope

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

## Feature: v2 frontend redesign

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

## Feature: Dependency security

- **Upgraded pdfjs-dist to 6.2.108, closing arbitrary JavaScript execution on opening a
  malicious PDF** (#194, GHSA-hq66-cqwq-w95j, HIGH). Also dompurify ≤3.4.12, where
  `CUSTOM_ELEMENT_HANDLING` bypasses `afterSanitizeElements` and `IN_PLACE` hook removal leaves
  a detached subtree executable (GHSA-c2j3-45gr-mqc4, GHSA-55q2-fjhq-7xh7). Found by
  `npm audit --omit=dev` on both SPAs — **`--omit=dev` is the part that matters**, because these
  are not build tooling: they ship to the browser. A platform whose entire purpose is ingesting
  untrusted documents cannot carry a parse-a-PDF-and-run-JS bug.

## Feature: Alt-text generation and grounding

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

## Feature: Test corpus and CI

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

## Feature: Remediation reaching the file

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

## Feature: Assessment correctness

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

## Feature: Multi-tenancy and the control plane

- Gave `documents` its own tenant column, separate from the business owner (#159). The table
  was not missing a tenant — `save_scan` and `handlers` were both landing one in `owner`. But
  `owner` is ADR 0003's document-*governance* column, sitting beside `department`,
  `business_criticality` and `regulatory_tags`: facts about the customer's document, not about
  which tenant owns the record. A "filter the estate by department" view has to be built on
  `documents`, since it is the only table carrying `department`.
- Added tenant-scoped estate aggregates for the control plane (#160).
- Built an estate view for a single tenant, and a Settings tab to read it (#165).

## Feature: Local model benchmarking

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

## Feature: docx Core-17 criterion coverage

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

## Feature: docx running header/footer parity

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

## Feature: Capability registry (ADR 0031)

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

## Feature: PHI privacy and document access control

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

## Feature: Continuous deployment to Azure

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

---

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
  are untracked in the working tree.
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
