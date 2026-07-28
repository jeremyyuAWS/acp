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

## How to change this rule

- **Office/PDF (docx, pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-3-1-1.js`](../../frontend/src/rules/wcag-3-1-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-critical-untagged-no-lang.pdf` | No tags, no title, no language, ambiguous link text — worst case |
| `test-corpus/files/pdf-serious-contrast.pdf` | Nearly-invisible light-grey text on white, no language |
| `test-corpus/files/pdf-moderate-mixed.pdf` | Has title but missing lang, abbreviations unexplained |
| `test-corpus/files/docx-clean-accessible.docx` | Full heading hierarchy, title set, lang set — should pass |
