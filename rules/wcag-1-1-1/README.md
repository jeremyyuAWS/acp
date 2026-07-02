# WCAG 1.1.1 — Non-text Content

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

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

## How to change this rule

- **Office/PDF (docx, pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-1-1-1.js`](../../frontend/src/rules/wcag-1-1-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-serious-ambiguous-links.docx` | Ambiguous link text (click here / read more), images without alt |
