# WCAG 2.4.6 — Headings and Labels

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.6 Headings and Labels (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/headings-and-labels.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `xlsx` | `XLSX-SHEET-002` | MODERATE | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/SheetNameUniquenessRule.cs` |
| `xlsx` | `XLSX-SHEET-001` | MODERATE | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/SheetNameRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-6.js`](../../frontend/src/rules/wcag-2-4-6.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_HEADING_SKIP` | docx | `api/office_structure.py:docx_checks` |
| `HTML_HEADING_SKIP` | html | `api/scanner.py:_analyse_html` |
| `PDF_NO_HEADINGS` | pdf | `api/office_structure.py:pdf_headings_labels_check` |
| `PPTX_TITLE_EMPTY` | pptx | `api/office_structure.py:pptx_checks` |
| `XLSX_DEFAULT_LABELS` | xlsx | `api/office_structure.py:xlsx_structure_checks` |

## How to change this rule

- **Office/PDF (xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-2-4-6.js`](../../frontend/src/rules/wcag-2-4-6.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/docx-moderate-skipped-headings.docx` | H1 → H3 (skips H2), otherwise well-structured |
| `test-corpus/files/docx-clean-accessible.docx` | Full heading hierarchy, title set, lang set — should pass |
