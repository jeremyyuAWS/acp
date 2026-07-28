# WCAG 1.2.3 — Audio Description or Media Alternative

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.2.3 Audio Description or Media Alternative (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/audio-description-or-media-alternative.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-1-2-3.js`](../../frontend/src/rules/wcag-1-2-3.js)
- Fix mode: `human-only`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-1-2-3.js`](../../frontend/src/rules/wcag-1-2-3.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
