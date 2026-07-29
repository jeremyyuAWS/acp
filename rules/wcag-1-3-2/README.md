# WCAG 1.3.2 — Meaningful Sequence

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.3.2 Meaningful Sequence (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/meaningful-sequence.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `pdf` | `pdf.reading-order` | MODERATE | human-only | `deploy/public/vendor/worker-python/analysers/rules/pdf/reading_order.py` |
| `pptx` | `PPTX-ORDER-001` | SERIOUS | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/ReadingOrderRule.cs` |
| `xlsx` | `XLSX-MERGE-001` | MODERATE | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/MergedCellsRule.cs` |
| `xlsx` | `XLSX-HIDDEN-001` | MODERATE | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/HiddenContentRule.cs` |
| `xlsx` | `XLSX-BLANK-001` | MODERATE | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/BlankWorksheetRule.cs` |

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_READING_ORDER_RISK` | docx | `api/office_structure.py:docx_checks` |

## How to change this rule

- **Office/PDF (pdf, pptx, xlsx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-borderline-contrast.pdf` | One slightly low-contrast section, otherwise OK |
