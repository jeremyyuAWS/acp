# WCAG 2.4.2 — Page Titled

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.2 Page Titled (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-TITLE-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/DocumentTitleRule.cs` |
| `docx` | `DOCX-BOOKMARK-001` | MINOR | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/BookmarksRule.cs` |
| `pdf` | `pdf.document-title` | SERIOUS | auto | `deploy/public/vendor/worker-python/analysers/rules/pdf/document_title.py` |
| `pdf` | `pdf.display-doc-title` | MODERATE | auto | `deploy/public/vendor/worker-python/analysers/rules/pdf/display_title.py` |
| `pdf` | `pdf.missing-bookmarks` | MINOR | auto | `deploy/public/vendor/worker-python/analysers/rules/pdf/bookmarks.py` |
| `pptx` | `PPTX-TITLE-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/SlideTitleRule.cs` |
| `xlsx` | `XLSX-TITLE-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/DocumentTitleRule.cs` |
| `xlsx` | `XLSX-SHEET-001` | MODERATE | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/SheetNameRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-2.js`](../../frontend/src/rules/wcag-2-4-2.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **Office/PDF (docx, pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-2-4-2.js`](../../frontend/src/rules/wcag-2-4-2.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-critical-untagged-no-lang.pdf` | No tags, no title, no language, ambiguous link text — worst case |
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/pptx-critical-no-titles.pptx` | Blank layout slides, no slide titles, low contrast, no semantic structure |
| `test-corpus/files/pdf-moderate-mixed.pdf` | Has title but missing lang, abbreviations unexplained |
| `test-corpus/files/pptx-moderate-title-only.pptx` | Has slide titles but no content placeholders, pseudo-bullets in textbox |
| `test-corpus/files/pdf-clean-accessible.pdf` | Title set, black text, no structural issues — should score 100 |
| `test-corpus/files/docx-clean-accessible.docx` | Full heading hierarchy, title set, lang set — should pass |
| `test-corpus/files/pptx-clean-accessible.pptx` | Title+Content layout, black text, proper structure — should pass |
