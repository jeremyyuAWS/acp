# ACP — comprehensive to-do

Snapshot as of `16581bd` (main, all three remotes in sync). Verified against
current source (`frontend/src/wcagCatalog.js`, `api/store.py` RULE_FORMATS,
`docs/adr/`) rather than carried forward from memory — every item below is
either a real, buildable gap or an explicit decision waiting on someone.

Current coverage (87 WCAG 2.1/2.2 success criteria):

| Bucket | Count | Meaning |
|---|---|---|
| Shipped (demo) | 33 | Real automated validator, verified backing |
| MDK HITL | 43 | Genuinely needs human judgment (captions, timing, error text, gesture alternatives, etc.) — correctly routed to the HITL queue, not a gap |
| Partner baseline | 6 | Covered by the .NET partner engine (`spike/dotnet/AcpScan.Cli`) |
| MDK net-new (Roadmap) | 5 | AAA/Optional, pure-media, non-automatable — explicitly deferred, not silently dropped |

No TODO/FIXME/XXX comments, no skipped tests, and no ADR left in Proposed/Draft
status anywhere in the repo — this file is the single backlog.

---

## P0 — Known bugs

None outstanding. The two correctness bugs found this session (duplicate
findings in FileDrawer, and the 10-SC false-PASS bug where several rules had
zero backend validator at all) are both fixed and committed (`92189ce`,
`db6326c`). If you hit something new, add it here before fixing it blind.

---

## P1 — Tier 2 format-coverage gaps (scoped out of the last pass, real work)

These are SCs that already have a **real validator for at least one format**
(so they show "Shipped" in the catalog) but are missing coverage for others.
Each is buildable with declared dependencies — no new pip packages needed.

1. **xlsx contrast (1.4.3 / 1.4.6)** — `api/office_structure.py` covers PDF
   contrast via pdfplumber's `non_stroking_color`; xlsx has no equivalent.
   Harder than PDF: a cell's true rendered color depends on the style index
   + any matching conditional-formatting rule, not just a direct fill/font
   color read — get this wrong and it's a false-positive machine on
   ordinary formatting (zebra-striping, header-row styling). Needs a
   deliberate design pass on how much of the style-resolution chain to
   implement before it's trustworthy enough to ship.
2. **pptx embedded-audio autoplay (1.4.2 Audio Control)** — HTML already
   detects autoplaying audio without a pause control; pptx slides can embed
   audio set to auto-advance/autoplay via `<p:timing>` and media relationship
   XML. Same posture as `office_structure.py`: read the slide XML directly,
   no partner dependency.
3. **docx/pptx form-field labeling (3.3.2 Labels or Instructions / 4.1.2
   Name, Role, Value)** — both are currently `frozenset({"html"})` only in
   `store.py`'s `RULE_FORMATS`. Word content controls (`<w:sdt>`) and
   legacy form fields (`<w:ffData>`) need a label/title check; pptx form
   controls are rare enough this may not be worth it standalone — bundle
   with the docx work and reassess.
4. **PDF outline-tree analog for 2.4.1 (Bypass Blocks)** — HTML has this
   via skip-links/landmarks; a PDF's equivalent is a populated
   `/Outlines` bookmark tree (or tagged-PDF structure tree) letting a
   screen-reader user jump past repeated content. `pikepdf` is already a
   declared dependency and can read `/Root/Outlines` directly — this is
   the most tractable of the four.

Suggested order: **#4 (PDF outline) → #2 (pptx audio) → #3 (form fields) →
#1 (xlsx contrast)**, roughly increasing implementation risk/false-positive
exposure.

---

## P2 — Decisions pending on the user (not blocked on engineering)

1. **Point `ACP_DRIVE_FOLDER` at Deva's folder** for scheduled sweeps —
   waiting on the folder ID.
2. **Measure real Ollama `llama3.1:8b` latency** in actual UI use (currently
   only confirmed healthy at the container level, revision
   `acp-ollama--v8b9ae76a1`, 0 restarts — never timed a live compliance-digest
   generation end-to-end).
3. **ADO review-cadence** — standing reviewer vs. bypass-as-needed for future
   PRs. Bypass-policies permission is already granted; this is a process
   choice, not a technical one.

---

## P3 — In-flight in another concurrent session — do not touch

A second autonomous session ("T") has uncommitted work sharing this same
checkout as of this snapshot. This is **not this backlog's to implement** —
listed here purely so nobody mistakes it for abandoned/stale work and reverts
it:

- Publish rewrite + per-file rescore (`api/handlers.py`, `api/routes/scans.py`,
  `api/store.py` — `record_publish`, `refresh_scan_aggregate`,
  `get_file_record`)
- DB-backed HITL queue touching several frontend views (`App.jsx`,
  `Dashboard.jsx`, `EmptyState.jsx`, `FileDrawer.jsx`, `Overview.jsx`,
  `Publish.jsx`, `Remediate.jsx`, `api.js`)
- Test-corpus reorg — deleting the 100 files under `test-corpus/files/` in
  favor of a new `test-corpus/bulk-200/` + `test-corpus/Legal sample files/`
  layout

If you're picking up this backlog cold and `git status` still shows these
paths modified, **stash them (`git stash push -u -m "..."`) before touching
`api/store.py` or any of the frontend files above** — don't edit over a
stash, and don't commit paths you didn't intend to touch. See the isolation-
dance pattern used for the `RULE_FORMATS` change in `16581bd` if `store.py`
needs another edit while T's WIP is still live: edit the working copy
in-place first, then build a separate clean-`HEAD`-based copy (same edits,
`assert count==1` string replace) to actually stage and commit, then restore
the mixed working copy afterward.

---

## Reference — where things live

- `api/office_structure.py` — first-party docx/pptx/pdf structural checks
  (2.4.6, 2.4.9, 1.4.3, 1.4.6); dispatcher is `checks_for(path, ext)`.
- `api/store.py` — `RULE_CATALOG` (the 87-ish rule list) + `RULE_FORMATS`
  (per-rule format applicability) + `_rule_outcome()` (PASS/FAIL/NOT_APPLICABLE).
- `tests/test_rule_formats.py` — contract test deriving `RULE_FORMATS` truth
  independently from source; extend `_derive_formats()`/`_OFFICE_STRUCT_FORMATS`
  whenever a P1 item above lands.
- `frontend/src/wcagCatalog.js` / `wcagCatalog.test.js` — the human-facing
  coverage table + its drift guard (source must be backed by a real validator,
  not just an aspirational label).
- `spike/dotnet/AcpScan.Cli/Program.cs` — the partner engine boundary; we
  cannot extend partner rules ourselves, only add first-party checks
  alongside them (the `office_structure.py` pattern).
