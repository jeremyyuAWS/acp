# WCAG 1.4.3 — Contrast (Minimum)

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.3 Contrast (Minimum) (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-CONTRAST-001` | SERIOUS | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/ColourContrastRule.cs` |
| `pptx` | `PPTX-CONTRAST-001` | SERIOUS | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/ColourContrastRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-4-3.js`](../../frontend/src/rules/wcag-1-4-3.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `PDF_LOW_CONTRAST_AA` | pdf | `api/office_structure.py:pdf_contrast_checks` |
| `PDF_TEXT_OVER_IMAGE` | pdf | `api/office_structure.py:pdf_text_over_image_checks` |
| `PPTX_LOW_CONTRAST_AA` | pptx | `api/office_structure.py:pptx_contrast_checks` |
| `PPTX_TEXT_OVER_COMPLEX_BG` | pptx | `api/office_structure.py:pptx_complex_bg_contrast_checks` |
| `SERIOUS` | pptx | `api/office_structure.py:pptx_contrast_checks` |
| `SERIOUS` | pdf | `api/office_structure.py:pdf_contrast_checks` |
| `SERIOUS` | xlsx | `api/office_structure.py:xlsx_contrast_checks` |
| `XLSX_LOW_CONTRAST_AA` | xlsx | `api/office_structure.py:xlsx_contrast_checks` |

## How to change this rule

- **Office/PDF (docx, pptx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-1-4-3.js`](../../frontend/src/rules/wcag-1-4-3.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/pptx-critical-no-titles.pptx` | Blank layout slides, no slide titles, low contrast, no semantic structure |
| `test-corpus/files/pdf-serious-contrast.pdf` | Nearly-invisible light-grey text on white, no language |
| `test-corpus/files/pdf-borderline-contrast.pdf` | One slightly low-contrast section, otherwise OK |
