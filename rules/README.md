# Rule ownership index

This directory is the **developer map of every accessibility rule** the platform
checks — one folder per WCAG 2.1 Success Criterion (SC). If you own a criterion,
your folder tells you exactly what is checked, by which engine, where the source
lives, how to change it, and which test fixtures cover it.

## How rules are actually implemented

Rules live in **four** places depending on the document type and on who wrote the
check. This index stitches them together so you don't have to know that to find your
way around:

| Engine | Language | Source of truth | What it covers |
|--------|----------|-----------------|----------------|
| **HTML (in-app)** | JS (deterministic) | [`frontend/src/rules/`](../frontend/src/rules/) — one `wcag-X-X-X.js` per SC | `.html` in the browser; live `check()` + `fix()` |
| **HTML (server)** | Python | [`api/scanner.py`](../api/scanner.py) → `_analyse_html` | `.html` `.htm` on every persisted scan — the `HTML_*` rules |
| **Office** | C# (partner DigitalA11y engine) | [`config/rule-catalog.json`](../config/rule-catalog.json) → `docx`/`pptx`/`xlsx` | `.docx` `.pptx` `.xlsx` |
| **PDF** | Python (worker-python engine) | [`config/rule-catalog.json`](../config/rule-catalog.json) → `pdf` | `.pdf` |

Layered on top of the engine results are ACP's **first-party Python checks**, which are
deliberately *not* in `rule-catalog.json` (that file is the ADR 0002 engine-rule contract:
A/AA only, one doc per rule, and several of these are AAA). They are read straight from
the code, so this index cannot drift from what actually runs:
[`api/office_structure.py`](../api/office_structure.py) (structure, dispatched per format
by `checks_for()`), [`api/textchecks.py`](../api/textchecks.py) (sensory, language-of-parts,
reading level), [`api/ocr.py`](../api/ocr.py) (images-of-text), and the migrated detectors
under [`api/formats/`](../api/formats/).

The two HTML rows are genuinely separate engines, not one described twice: the in-app
modules run in the browser and back the live preview, while `_analyse_html` is what a
server-side scan records. A criterion can be covered by one and not the other, and the
per-SC pages below say which.

The per-SC READMEs here are **generated** from those sources by
[`scripts/gen_rules_index.py`](../scripts/gen_rules_index.py). After any rule
change, run:

```bash
python scripts/gen_rules_index.py
```

A machine-readable version is at [`rules/index.json`](./index.json) (used by CI and
tooling). **This file** (`rules/README.md`) is hand-written prose, with one exception:
the ownership table below sits between generated markers, and the same command rewrites
its criteria list and Engines column. **Your Owner entry is preserved** — it is parsed
out and written back — so claim a criterion by editing the table and re-running is safe.
Keeping the owner current is a human job; keeping the derived columns current is not.

## The single rule-ID convention

Everything is keyed by **WCAG SC number** (`1.4.3`), end to end. Engine-specific IDs
(`DOCX-CONTRAST-001`, `pdf.missing-alt-text`) are an implementation detail that maps
*to* the SC via the `wcag_sc` field in the catalog and `_extract_sc()` in
[`api/store.py`](../api/store.py). When you see a finding, trace it: engine rule ID →
`wcag_sc` → this folder.

## Ownership

Claim a criterion by putting your name in the Owner column. Owning an SC means you're
the reviewer for any change to its detection or remediation, across all engines.

<!-- BEGIN GENERATED: ownership table (scripts/gen_rules_index.py) -->
| Success Criterion | Level | Engines | Owner |
|-------------------|-------|---------|-------|
| [1.1.1 Non-text Content](./wcag-1-1-1/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [1.2.1 Audio-only & Video-only (Prerecorded)](./wcag-1-2-1/) | A | html | _unassigned_ |
| [1.2.2 Captions (Prerecorded)](./wcag-1-2-2/) | A | html | _unassigned_ |
| [1.2.3 Audio Description or Media Alternative](./wcag-1-2-3/) | A | html | _unassigned_ |
| [1.3.1 Info and Relationships](./wcag-1-3-1/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [1.3.2 Meaningful Sequence](./wcag-1-3-2/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [1.3.3 Sensory Characteristics](./wcag-1-3-3/) | A | docx, pdf, pptx, xlsx | _unassigned_ |
| [1.3.4 Orientation](./wcag-1-3-4/) | AA | html | _unassigned_ |
| [1.3.5 Identify Input Purpose](./wcag-1-3-5/) | AA | html | _unassigned_ |
| [1.4.1 Use of Color](./wcag-1-4-1/) | A | docx, html, pdf, xlsx | _unassigned_ |
| [1.4.2 Audio Control](./wcag-1-4-2/) | A | html, pptx | _unassigned_ |
| [1.4.3 Contrast (Minimum)](./wcag-1-4-3/) | AA | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [1.4.4 Resize Text](./wcag-1-4-4/) | AA | html, pptx | _unassigned_ |
| [1.4.5 Images of Text](./wcag-1-4-5/) | AA | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [1.4.6 Contrast (Enhanced)](./wcag-1-4-6/) | AAA | html, pdf, pptx, xlsx | _unassigned_ |
| [1.4.8 Visual Presentation](./wcag-1-4-8/) | AAA | docx | _unassigned_ |
| [1.4.9 Images of Text (No Exception)](./wcag-1-4-9/) | AAA | docx, pdf, pptx, xlsx | _unassigned_ |
| [1.4.10 Reflow](./wcag-1-4-10/) | AA | docx, html, pptx | _unassigned_ |
| [1.4.11 Non-text Contrast](./wcag-1-4-11/) | AA | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [1.4.12 Text Spacing](./wcag-1-4-12/) | AA | docx, html, pdf, pptx | _unassigned_ |
| [2.1.1 Keyboard](./wcag-2-1-1/) | A | html, pptx | _unassigned_ |
| [2.1.2 No Keyboard Trap](./wcag-2-1-2/) | A | docx, pptx, xlsx | _unassigned_ |
| [2.4.1 Bypass Blocks](./wcag-2-4-1/) | A | html, pdf | _unassigned_ |
| [2.4.2 Page Titled](./wcag-2-4-2/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [2.4.3 Focus Order](./wcag-2-4-3/) | A | html, pdf, pptx | _unassigned_ |
| [2.4.4 Link Purpose (In Context)](./wcag-2-4-4/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [2.4.6 Headings and Labels](./wcag-2-4-6/) | AA | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [2.4.7 Focus Visible](./wcag-2-4-7/) | AA | html | _unassigned_ |
| [2.4.9 Link Purpose (Link Only)](./wcag-2-4-9/) | AAA | docx, html, pptx | _unassigned_ |
| [2.4.10 Section Headings](./wcag-2-4-10/) | AAA | docx | _unassigned_ |
| [2.5.3 Label in Name](./wcag-2-5-3/) | A | html | _unassigned_ |
| [2.5.8 Target Size (Minimum)](./wcag-2-5-8/) | AA | html | _unassigned_ |
| [3.1.1 Language of Page](./wcag-3-1-1/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
| [3.1.2 Language of Parts](./wcag-3-1-2/) | AA | docx, pdf, pptx, xlsx | _unassigned_ |
| [3.1.4 Abbreviations](./wcag-3-1-4/) | AAA | html | _unassigned_ |
| [3.1.5 Reading Level](./wcag-3-1-5/) | AAA | docx, pdf, pptx, xlsx | _unassigned_ |
| [3.3.2 Labels or Instructions](./wcag-3-3-2/) | A | docx, html | _unassigned_ |
| [4.1.2 Name, Role, Value](./wcag-4-1-2/) | A | docx, html, pdf, pptx, xlsx | _unassigned_ |
<!-- END GENERATED: ownership table -->

## Adding a new rule

1. **HTML (in-app):** create `frontend/src/rules/wcag-X-X-X.js` (copy an existing
   module), export `meta` + `check` + `fix`, import it in `frontend/src/rules/index.js`.
2. **HTML (server):** emit the finding from `_analyse_html` in `api/scanner.py`, and
   register the matching fixer in `api/remediate.py`. A rule emitted anywhere else in
   `scanner.py` will fail the generator until you declare its function and formats in
   `_SCANNER_SOURCES` — that is deliberate, so it cannot go undocumented.
3. **Office/PDF:** add the rule entry to `config/rule-catalog.json` under the engine,
   with `wcag_sc`, `severity`, `fix_mode`, and the engine `source` path.
4. **First-party Python:** add the check to `api/office_structure.py` and dispatch it in
   `checks_for()` (a check that is never dispatched is not coverage), or to
   `api/textchecks.py` / `api/ocr.py` / `api/formats/<fmt>/detectors/`.
5. Add a fixture to `test-corpus/` that triggers it, and note it in
   `test-corpus/manifest.json`.
6. Run `python scripts/gen_rules_index.py` and commit the regenerated folder — including
   the ownership table in this file, which the same command rewrites.

## Fix modes

- `auto` — deterministic engine fix, applied without human review.
- `ai-assisted` — engine drafts a fix, a human approves it (routed to the HITL queue
  when AI is **on**; routed straight to HITL as `human-only` when AI is **off** —
  see the AI toggle in the app header).
- `human-only` — must be verified by a person; never auto-applied.
