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
| `test-corpus/files/pdf-critical-untagged-no-lang.pdf` | No tags, no title, no language, ambiguous link text — worst case |
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/pdf-serious-contrast.pdf` | Nearly-invisible light-grey text on white, no language |
| `test-corpus/files/docx-serious-ambiguous-links.docx` | Ambiguous link text (click here / read more), images without alt |
| `test-corpus/files/pptx-moderate-title-only.pptx` | Has slide titles but no content placeholders, pseudo-bullets in textbox |
| `test-corpus/files/pdf-clean-accessible.pdf` | Title set, black text, no structural issues — should score 100 |
| `test-corpus/files/pptx-clean-accessible.pptx` | Title+Content layout, black text, proper structure — should pass |
