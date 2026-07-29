# WCAG 4.1.2 — Name, Role, Value

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 4.1.2 Name, Role, Value (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-4-1-2.js`](../../frontend/src/rules/wcag-4-1-2.js)
- Fix mode: `ai-assisted`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_FORM_FIELD_NO_TAG` | docx | `api/office_structure.py:docx_checks` |
| `OFFICE_INTERACTIVE_CONTROL_NAME_ROLE` | docx, pptx, xlsx | `api/office_structure.py:office_control_review_checks` |
| `PDF_FORM_NO_ACCESSIBLE_NAME` | pdf | `api/formats/pdf/detectors/name_role_value.py` |
| `PDF_FORM_NO_FIELD_TYPE` | pdf | `api/formats/pdf/detectors/name_role_value.py` |
| `PDF_FORM_REQUIRED_NO_VALUE` | pdf | `api/formats/pdf/detectors/name_role_value.py` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-4-1-2.js`](../../frontend/src/rules/wcag-4-1-2.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
