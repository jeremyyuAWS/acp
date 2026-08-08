# WCAG 1.1.1 — Non-text Content

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.1.1 Non-text Content (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-ALT-001` | CRITICAL | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/AltTextRule.cs` |
| `pdf` | `pdf.missing-alt-text` | CRITICAL | auto | `deploy/public/vendor/worker-python/analysers/rules/pdf/image_alt_text.py` |
| `pptx` | `PPTX-ALT-001` | CRITICAL | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/AltTextRule.cs` |
| `xlsx` | `XLSX-ALT-001` | CRITICAL | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/AltTextRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-1-1.js`](../../frontend/src/rules/wcag-1-1-1.js)
- Fix mode: `ai-assisted`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_IMAGE_NO_ALT` | docx | `api/formats/docx/detectors/non_text_content.py` |
| `HTML_IMG_MISSING_ALT` | html | `api/scanner.py:_analyse_html` |
| `PDF_FIGURE_NO_ALT` | pdf | `api/formats/pdf/detectors/non_text_content.py` |
| `PPTX_IMAGE_NO_ALT` | pptx | `api/formats/pptx/detectors/non_text_content.py` |
| `XLSX_IMAGE_NO_ALT` | xlsx | `api/formats/xlsx/detectors/non_text_content.py` |

## How to change this rule

- **Office/PDF (docx, pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-1-1-1.js`](../../frontend/src/rules/wcag-1-1-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-compliant.docx` | title+lang+alt+header row+descriptive link; expect ~0 issues, high score |
| `test-corpus/files/docx-moderate.docx` | title+lang OK; missing alt + generic link text |
| `test-corpus/files/docx-noncompliant.docx` | no title/lang, missing alt, generic link, table w/o header — many SERIOUS/CRITICAL |
| `test-corpus/files/pptx-compliant.pptx` | slide title + image alt + language; expect ~0 issues |
| `test-corpus/files/pptx-noncompliant.pptx` | no slide title, image w/o alt, no language (rule ids approximate) |
