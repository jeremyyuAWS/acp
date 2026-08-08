# WCAG 3.1.1 — Language of Page

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 3.1.1 Language of Page (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-LANG-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/DocumentLanguageRule.cs` |
| `pdf` | `pdf.document-language` | SERIOUS | auto | `deploy/public/vendor/worker-python/analysers/rules/pdf/document_language.py` |
| `pptx` | `PPTX-LANG-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/DocumentLanguageRule.cs` |
| `xlsx` | `XLSX-LANG-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/DocumentLanguageRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-3-1-1.js`](../../frontend/src/rules/wcag-3-1-1.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `HTML_MISSING_LANG` | html | `api/scanner.py:_analyse_html` |
| `HTML_MISSING_LANG` | html | `api/formats/html/detectors/language_of_page.py` |

## How to change this rule

- **Office/PDF (docx, pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-3-1-1.js`](../../frontend/src/rules/wcag-3-1-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-compliant.docx` | title+lang+alt+header row+descriptive link; expect ~0 issues, high score |
| `test-corpus/files/docx-moderate.docx` | title+lang OK; missing alt + generic link text |
| `test-corpus/files/docx-noncompliant.docx` | no title/lang, missing alt, generic link, table w/o header — many SERIOUS/CRITICAL |
| `test-corpus/files/docx-empty.docx` | empty body but title+lang set; tests empty-content handling, expect ~0 issues |
| `test-corpus/files/pptx-compliant.pptx` | slide title + image alt + language; expect ~0 issues |
| `test-corpus/files/pptx-noncompliant.pptx` | no slide title, image w/o alt, no language (rule ids approximate) |
| `test-corpus/files/xlsx-compliant.xlsx` | named sheet + title + lang + header row; expect ~0 issues |
| `test-corpus/files/xlsx-noncompliant.xlsx` | no title/lang, generic 'Sheet' name, merged cells, hidden sheet (rule ids approximate) |
| `test-corpus/files/pdf-untagged.pdf` | untagged + no title + no /Lang (rule ids approximate) |
| `test-corpus/files/pdf-titled-lang.pdf` | title + /Lang set, but still untagged — title/lang pass, tagging fails |
