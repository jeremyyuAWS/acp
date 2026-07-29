# WCAG 1.4.10 — Reflow

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.10 Reflow (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/reflow.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-4-10.js`](../../frontend/src/rules/wcag-1-4-10.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `HTML_NO_VIEWPORT_REFLOW` | html | `api/scanner.py:_analyse_html` |
| `OFFICE_WIDE_TABLE_REFLOW` | docx, pptx | `api/office_structure.py:office_reflow_checks` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-1-4-10.js`](../../frontend/src/rules/wcag-1-4-10.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
