# WCAG 1.4.4 — Resize Text

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.4 Resize Text (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/resize-text.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-4-4.js`](../../frontend/src/rules/wcag-1-4-4.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `PPTX_FIXED_TEXT_BOX_RESIZE` | pptx | `api/office_structure.py:pptx_resize_text_checks` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-1-4-4.js`](../../frontend/src/rules/wcag-1-4-4.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
