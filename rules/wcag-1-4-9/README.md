# WCAG 1.4.9 — Images of Text (No Exception)

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.9 Images of Text (No Exception) (Level AAA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/images-of-text-no-exception.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `OCR_IMAGE_OF_TEXT_STRICT` | docx, pdf, pptx, xlsx | `api/ocr.py` |

## How to change this rule

- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
