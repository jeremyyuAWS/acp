# WCAG 2.4.1 — Bypass Blocks

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.1 Bypass Blocks (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/bypass-blocks.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-1.js`](../../frontend/src/rules/wcag-2-4-1.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `HTML_NO_SKIP_LINK` | html | `api/scanner.py:_analyse_html` |
| `PDF_NO_BOOKMARKS` | pdf | `api/office_structure.py:pdf_bypass_blocks_check` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-2-4-1.js`](../../frontend/src/rules/wcag-2-4-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
