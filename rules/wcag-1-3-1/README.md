# WCAG 1.3.1 — Info and Relationships

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.3.1 Info and Relationships (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-TABLE-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/TableHeaderRule.cs` |
| `docx` | `DOCX-HEAD-001` | MODERATE | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/HeadingStructureRule.cs` |
| `pdf` | `pdf.tagged` | SERIOUS | human-only | `deploy/public/vendor/worker-python/analysers/rules/pdf/tagged_pdf.py` |
| `pptx` | `PPTX-TABLE-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/TableHeaderRule.cs` |
| `xlsx` | `XLSX-TABLE-001` | SERIOUS | auto | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/TableHeaderRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-3-1.js`](../../frontend/src/rules/wcag-1-3-1.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **Office/PDF (docx, pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-1-3-1.js`](../../frontend/src/rules/wcag-1-3-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/pptx-critical-no-titles.pptx` | Blank layout slides, no slide titles, low contrast, no semantic structure |
| `test-corpus/files/docx-moderate-skipped-headings.docx` | H1 → H3 (skips H2), otherwise well-structured |
| `test-corpus/files/docx-clean-accessible.docx` | Full heading hierarchy, title set, lang set — should pass |
| `test-corpus/files/pptx-clean-accessible.pptx` | Title+Content layout, black text, proper structure — should pass |
