# WCAG 2.1.1 — Keyboard

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.1.1 Keyboard (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/keyboard.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### Office & PDF engines

| Engine | Rule ID | Severity | Fix mode | Source |
|--------|---------|----------|----------|--------|
| `pptx` | `PPTX-ANIM-001` | MODERATE | human-only | `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/AnimationOrderRule.cs` |

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-1-1.js`](../../frontend/src/rules/wcag-2-1-1.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **Office/PDF (pptx):** the detection logic lives in the partner DigitalA11y engine (see `source` paths above). You own the *mapping and parameters* here, not the .NET source. To change a threshold or disable a rule, edit `config/rule-catalog.json` and/or the active rubric (`config/rubric.active.json` → `disabled_rules`).
- **HTML:** edit [`frontend/src/rules/wcag-2-1-1.js`](../../frontend/src/rules/wcag-2-1-1.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

_No dedicated fixture yet — add one to `test-corpus/` and regenerate._
