# ACP Sprint Backlog — Coverage depth, adapter completeness, disposition intelligence

Grounded in a gap analysis of `origin/main` as of 2026-09-04. Every item names the specific file
and line where the gap lives; nothing here is a wish. The previous sprint backlog
(`docs/hitl-review-ux-backlog.md`) is fully shipped and is the immediate baseline.

**The sprint's three axes:**

1. **Close backend gaps behind wired UIs** — three frontend surfaces are complete but stall on
   missing backend routes or a flag that was never flipped.
2. **Complete the AI provider adapter set** — Gemini and Bedrock remain disabled in `Settings.jsx`
   (`ADAPTER_READY` set, `api/providers.py`); the existing OpenAI adapter is the template.
3. **Deepen coverage and corroboration** — veraPDF Phase 0 closes the largest honest PDF gap;
   AcroForm field-type extension closes a bounded 2.5.3 hole; scanned-PDF Tier A opens the GPU
   assessment path.

**Sequencing note:** P0 items are bounded single-PR builds with no external dependencies. P1 items
each depend on one decision or prior ship. P2 items are multi-PR arcs; only their entry slice is
scheduled here — each is bookmarked so the next sprint can pick up the thread.

---

## P0 — Close the backend gap behind wired UIs (small, no blockers)

- [x] **Criterion disposition persistence backend.** `frontend/src/api.js:1632–1648` has a
  `// BACKEND DEFERRED` comment on `disposeCriterion` / `listDispositions`. The File Drawer's "W4"
  flow (reviewer attests a criterion as out-of-scope or manually verified) is fully wired in the
  frontend — `POST /scans/{sid}/files/{file}/dispose` and `GET .../dispositions` — but neither
  route exists. Dispositions are lost on reload; reviewers doing per-criterion scope exceptions
  have no persistence. Pattern: follow existing `decision_log` dual-write routes in
  `api/routes/scans.py`. **Two backend routes + a store method + structural tests.**
  ✅ Routes, store methods, DB table, and 20-test suite (`tests/test_criterion_disposition.py`) landed.

- [x] **Auto-apply gate for 2.4.4 and 4.1.2 (ADR 0041).** ADR 0041 (`docs/adr/`) is Accepted;
  the implementation step is exactly one check per applier: `apply_alt.py` (and its 2.4.4
  link-text / 4.1.2 accessible-name counterparts) check `hitl_queue.validated=True` — set by
  the structural verifier — before deciding to auto-apply vs. route to the human queue. Extends
  the auto-apply path beyond the current OCR-anchored alt path. **One gate condition per applier
  + routing tests asserting both branches fire correctly.**
  ✅ Merged as #1327 — gate in `handlers._enqueue_proposals`, `store.auto_approve_proposals`, 21 tests.

- [x] **Folder/path match field in the disposition rule engine.** `api/disposition.py` has no
  `path` or `folder` match condition. The SharePoint walk already fetches `parentReference`
  (folder path) per item. Adding a `folder_path_contains` condition to the rule engine enables
  UTSW's folder-based archival rules. Named a "small build" in `docs/sharepoint-gaps.md`.
  **One new match field in `disposition.py` + tests.**
  ✅ Built 2026-09-04 — `path`, `parent_folder`, `prefix`/`contains` ops, tested in `test_disposition_conditions.py`.

---

## P1 — Adapter completeness and corroboration (medium, each gated on one decision)

- [ ] **Gemini vision adapter.** `frontend/src/Settings.jsx:657` disables Gemini's checkbox —
  `ADAPTER_READY` does not include `'gemini'`. No `GeminiVisionProvider` exists in
  `api/providers.py`. The OpenAI adapter is the direct template: Gemini exposes an
  OpenAI-compatible endpoint. Ship `GeminiVisionProvider`, add `'gemini'` to `ADAPTER_READY`,
  wire the same safe synthetic probe (`probe_image_bytes()`) and the same Langfuse attribution
  path used by the OpenAI adapter. Security constraints from ADR 0019 apply: token never in DB,
  response body, log, or trace.

- [ ] **Bedrock vision adapter.** Same gap as Gemini above but Bedrock requires AWS SigV4 request
  signing instead of a bearer token. Ship `BedrockVisionProvider`, add `'bedrock'` to
  `ADAPTER_READY`, wire SigV4 via `boto3.request.AWSRequest` (the pattern already used in the
  existing AWS integration path). Same probe + attribution constraints apply.

- [ ] **veraPDF Phase 0 — local corroboration engine.** `docs/adr/0028-amendment-local-corroboration-engines.md`
  and `docs/spikes/2026-07-17-verapdf-spike.md` document a complete spike. veraPDF (MPL-2.0)
  corroborates ACP's 1.3.1 / 2.4.2 / 3.1.1 PDF findings with per-content-item granularity.
  Two paths: **RECORDED** (pre-captured JSON, always-on in CI — no binary needed), **LIVE**
  (containerised `verapdf/rest`, production). Spike code is in place; the remaining steps are
  wiring the RECORDED path into the test suite and the LIVE path behind a feature flag. Requires
  no document egress and no licensing overhead beyond veraPDF's MPL-2.0. Adds corroborating
  evidence to three criteria without fabricating new detection.

- [ ] **2.5.3 AcroForm field types in PDF.** `api/remediate_pdf.py`'s `pdf_form_field_checks()`
  covers pushbutton and list-box AcroForm fields but not text inputs, checkboxes, or radio
  buttons. These are the majority of real form fields and each has a label-linkage check
  (explicit `/TU` tooltip vs. adjacent text heuristic). Extend `pdf_form_field_checks()` to
  cover all five AcroForm field types. **Bounded native build; capability registry update +
  structural test with a real-form fixture.**

---

## P2 — Strategic entry slices (multi-PR arcs; only the first slice is scheduled)

- [ ] **Enterprise Review Memory — derivation job + Settings panel (ADR 0021, Slice 1).** The
  data model is in place (`api/store.py`'s `org_memory` table, `add_org_memory`,
  `list_org_memory`, `memory_guidance` methods exist). The feature flag is `ACP_REVIEW_MEMORY=off`.
  Two things are missing: (a) the **nightly derivation job** — reads `hitl_events`, proposes
  rules when ≥10 approvals + edit-rate signal are met, using the same thresholds as
  `hitl_analytics()` (`_MATURITY_MIN_APPROVALS`, `_MATURITY_MAX_EDIT_RATE`) — follow the
  `sweeper.py` cron pattern; (b) the **Settings → Review Memory panel** — proposed-rules list,
  accept/reject UI, the "house style applied" chip on proposal cards (ADR 0021 §E). Ship both
  behind the flag; flip the flag only after end-to-end test with real `hitl_events` rows.

- [ ] **GPU scanned-PDF assessment — Tier A entry slice (ADR 0027).** Scanned / untagged PDFs
  return `not_evaluated` on nearly every criterion — the single largest honest coverage gap.
  ADR 0027 (Status: Proposed) defines a three-tier build; Tier A is the entry slice: (1) detect
  untagged / scanned PDFs at assess time (`/Tags` absent, text extraction yield < threshold);
  (2) route them to a vision layout call (`describe_image_structured`) that returns a layout
  model (heading regions, text blocks, image regions, tables); (3) surface the layout model in
  the file drawer as "extracted structure" without yet mapping it to per-criterion findings
  (that is Tier B). Tier A proves the detection gate and the layout call before any finding
  mapping is attempted. Ship Tier A behind a `ACP_SCANNED_PDF_TIER_A` flag.

- [ ] **Tagged accessible conformance report — WeasyPrint migration (ADR 0034, spike validation).**
  The conformance report handed to audit teams **fails its own tagged-PDF check** (a test in the
  suite pins this deliberately: `test_untagged_is_still_the_open_finding`). ADR 0034 selects
  WeasyPrint as the replacement for ReportLab; a bounded spike passed structural checks and lives
  in `spike/weasyprint-report/`. The remaining gate before a full `report.py` migration is: (1)
  run the spike output through veraPDF/PAC and confirm PDF/UA-1 structural pass; (2) visual
  diff of representative report pages (hospital letterhead, evidence tables, chart embeds).
  **This sprint: run the gate — produce the two validation artefacts. Full migration is the
  follow-on.**

---

## Dependency — unblocks two P1/P2 items

- [ ] **SharePoint native metadata reads (`listItem/fields`).** `docs/sharepoint-gaps.md` names
  this a "medium build" gated on SOW sign-off. The SharePoint walk reads file basics and folder
  path but not managed metadata, content types, or sensitivity labels. One additional Graph API
  call per item (`GET /drives/{d}/items/{id}/listItem?expand=fields&select=...`) within existing
  read-only scopes. Unblocks: (a) disposition rules keyed on SharePoint native columns (folder
  rule, item 3 above, is partially satisfied already; content-type rules require this); (b)
  document-type scoping in Discover (BACKLOG P2.3 — the `file_records.department` column has no
  scan-derived source without this). **Gated on SOW sign-off; not started until that arrives.**

---

### Not scheduled this sprint

- P5.4 mutation testing — infrastructure decision first (no runner in the venv)
- Azure agent pool (I.1) — admin action, zero engineering
- ACR Phase 5 VPAT export — gated on ITI licensing decision
- Managed workspace remediation wiring — post-workspace-pilot
- ADR 0032 SMB Phase 2 hardening — post-pilot
- WeasyPrint full `report.py` migration — gated on the Tier A validation sprint above
- Portable deployment Phases 2–5 — post-Phase 1 container stabilisation
