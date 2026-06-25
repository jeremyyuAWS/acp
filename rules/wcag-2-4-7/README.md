# WCAG 2.4.7 — Focus Visible

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.7 Focus Visible (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/focus-visible.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-7.js`](../../frontend/src/rules/wcag-2-4-7.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-2-4-7.js`](../../frontend/src/rules/wcag-2-4-7.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
