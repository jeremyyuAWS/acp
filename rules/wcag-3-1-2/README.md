# WCAG 3.1.2 — Language of Parts

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 3.1.2 Language of Parts (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/language-of-parts.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `docx` | `DOCX-LANGPART-001` | MODERATE | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/LanguageOfPartsRule.cs` |

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `LANG_PARTS_UNMARKED` | docx, pdf, pptx, xlsx | `api/textchecks.py` |

## How to change this rule

- **Office/PDF (docx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pptx-compliant.pptx` | slide title + image alt + language; expect ~0 issues |
| `test-corpus/files/pptx-noncompliant.pptx` | no slide title, image w/o alt, no language (rule ids approximate) |
