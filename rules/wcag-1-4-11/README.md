# WCAG 1.4.11 — Non-text Contrast

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.11 Non-text Contrast (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-4-11.js`](../../frontend/src/rules/wcag-1-4-11.js)
- Fix mode: `ai-assisted`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_NONTEXT_LOW_CONTRAST` | docx | `api/office_structure.py:docx_nontext_contrast_checks` |
| `HTML_BORDER_LOW_CONTRAST` | html | `api/scanner.py:_analyse_html` |
| `PDF_NONTEXT_LOW_CONTRAST` | pdf | `api/office_structure.py:pdf_nontext_contrast_checks` |
| `PPTX_NONTEXT_LOW_CONTRAST` | pptx | `api/office_structure.py:pptx_nontext_contrast_checks` |
| `XLSX_NONTEXT_LOW_CONTRAST` | xlsx | `api/office_structure.py:xlsx_nontext_contrast_checks` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-1-4-11.js`](../../frontend/src/rules/wcag-1-4-11.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
