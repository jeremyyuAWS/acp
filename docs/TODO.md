# ACP — comprehensive to-do

Snapshot as of `5ec86b6` (main, all three remotes in sync). Verified against
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

Three of four shipped (`22a7202`, `a916068`, `5ec86b6`); one is genuinely
blocked, not just deferred. Each landed with real fixtures verified before
implementing — no guessed detection logic.

1. ~~**PDF outline-tree analog for 2.4.1 (Bypass Blocks)**~~ — SHIPPED
   (`22a7202`). `pdf_bypass_blocks_check()` in `office_structure.py`, via
   pikepdf's `/Root/Outlines`. Only checked at 5+ pages (a short memo has no
   real bypass-blocks problem).
2. **pptx embedded-audio autoplay (1.4.2 Audio Control)** — BLOCKED. Verified
   the audio-attachment marker (`<a:audioFile r:link="rId">` inside
   `<p:nvPr>`) via Microsoft's own Open XML SDK docs, but could not verify
   the exact `<p:timing>` trigger-condition XML that distinguishes autoplay
   from click-to-play — Microsoft's docs don't spell it out precisely, and
   no PowerPoint/LibreOffice is available in this environment to generate a
   real ground-truth fixture. Do not implement this from memory/guesswork —
   next attempt needs either a real PowerPoint install somewhere, or a
   donated real autoplay-audio .pptx to inspect.
3. ~~**docx/pptx form-field labeling (3.3.2 / 4.1.2)**~~ — SHIPPED
   (`a916068`), docx only. `docx_checks()` flags content-control form fields
   (checkbox/date/dropdown/comboBox/picture — the unambiguous input gallery
   types) missing a `w:alias` title. Verified against 3 independent sources
   that `w:sdt` also wraps non-form content (TOC blocks, citations) that
   must NOT be flagged — pptx form controls were assessed as too rare to be
   worth a separate pass. Ships as 3.3.2 only, not 4.1.2 (4.1.2 is broader
   than just labeling and wasn't fully verified as covered).
4. ~~**xlsx contrast (1.4.3 / 1.4.6)**~~ — SHIPPED (`5ec86b6`), deliberately
   narrow. `xlsx_contrast_checks()` resolves cell font/fill color through
   `xl/styles.xml`'s cellXfs → fonts/fills chain, but ONLY direct
   `<color rgb="...">` — theme= and indexed= colors, and non-solid pattern
   fills, resolve to "unknown" and are skipped rather than guessed at (theme
   colors are exactly what Excel's built-in header/table styles use).
   Conditional-formatting (`cfRule`) overrides are out of scope entirely.

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

**Gotcha hit during the P1 work (`a916068`):** the "save the mixed copy"
step must happen *after* editing the working copy in place, not before —
saving it first and editing second means the later restore silently reverts
your own edit from the working tree even though the commit itself is fine
(git history stays correct; only the local file drifts). `test_rule_formats.py`
caught this immediately on the next isolation dance because the derived
truth no longer matched `RULE_FORMATS` — that's exactly the kind of drift
the contract test exists to catch, but don't rely on it; get the copy order
right: **edit in place → save mixed copy → build clean-HEAD copy → commit →
restore mixed copy**.

---

## Reference — where things live

- `api/office_structure.py` — first-party docx/pptx/pdf/xlsx structural
  checks (2.4.6, 2.4.9, 1.4.3, 1.4.6, 2.4.1, 3.3.2); dispatcher is
  `checks_for(path, ext)`.
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
