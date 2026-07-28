# WCAG 1.4.6 — Contrast (Enhanced)

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.6 Contrast (Enhanced) (Level AAA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/contrast-enhanced.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-4-6.js`](../../frontend/src/rules/wcag-1-4-6.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `MODERATE` | pptx | `api/office_structure.py:pptx_contrast_checks` |
| `MODERATE` | pdf | `api/office_structure.py:pdf_contrast_checks` |
| `MODERATE` | xlsx | `api/office_structure.py:xlsx_contrast_checks` |
| `PDF_LOW_CONTRAST_AAA` | pdf | `api/office_structure.py:pdf_contrast_checks` |
| `PPTX_LOW_CONTRAST_AAA` | pptx | `api/office_structure.py:pptx_contrast_checks` |
| `XLSX_LOW_CONTRAST_AAA` | xlsx | `api/office_structure.py:xlsx_contrast_checks` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-1-4-6.js`](../../frontend/src/rules/wcag-1-4-6.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/pptx-critical-no-titles.pptx` | Blank layout slides, no slide titles, low contrast, no semantic structure |
| `test-corpus/files/pdf-serious-contrast.pdf` | Nearly-invisible light-grey text on white, no language |
| `test-corpus/files/pdf-borderline-contrast.pdf` | One slightly low-contrast section, otherwise OK |
