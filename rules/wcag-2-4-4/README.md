# WCAG 2.4.4 — Link Purpose (In Context)

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.4 Link Purpose (In Context) (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-LINK-001` | MODERATE | ai-assisted | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/LinkPurposeRule.cs` |
| `pptx` | `PPTX-LINK-001` | MODERATE | ai-assisted | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/LinkPurposeRule.cs` |
| `xlsx` | `XLSX-LINK-001` | MODERATE | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/LinkPurposeRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-4.js`](../../frontend/src/rules/wcag-2-4-4.js)
- Fix mode: `ai-assisted`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_LINK_PURPOSE_VAGUE` | docx | `api/office_structure.py:docx_checks` |
| `PDF_LINK_RAW_URL` | pdf | `api/office_structure.py:pdf_link_purpose_check` |
| `PPTX_LINK_PURPOSE_VAGUE` | pptx | `api/office_structure.py:pptx_checks` |
| `XLSX_LINK_PURPOSE_VAGUE` | xlsx | `api/office_structure.py:xlsx_structure_checks` |

## How to change this rule

- **Office/PDF (docx, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-2-4-4.js`](../../frontend/src/rules/wcag-2-4-4.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-critical-untagged-no-lang.pdf` | No tags, no title, no language, ambiguous link text — worst case |
| `test-corpus/files/docx-serious-ambiguous-links.docx` | Ambiguous link text (click here / read more), images without alt |
