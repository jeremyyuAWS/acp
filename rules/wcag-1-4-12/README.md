# WCAG 1.4.12 — Text Spacing

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.12 Text Spacing (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/text-spacing.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-4-12.js`](../../frontend/src/rules/wcag-1-4-12.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `HTML_FIXED_LINE_HEIGHT` | html | `api/scanner.py:_analyse_html` |
| `OFFICE_EXACT_LINE_SPACING` | docx, pptx | `api/office_structure.py:office_text_spacing_checks` |
| `PDF_TIGHT_LINE_SPACING` | pdf | `api/office_structure.py:pdf_text_spacing_checks` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-1-4-12.js`](../../frontend/src/rules/wcag-1-4-12.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-moderate.docx` | title+lang OK; missing alt + generic link text |
| `test-corpus/files/edge-plaintext.docx` | plain text with .docx extension; should fail gracefully |
