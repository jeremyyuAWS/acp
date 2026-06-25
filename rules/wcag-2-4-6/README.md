# WCAG 2.4.6 — Headings and Labels

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.6 Headings and Labels (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/headings-and-labels.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-6.js`](../../frontend/src/rules/wcag-2-4-6.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-2-4-6.js`](../../frontend/src/rules/wcag-2-4-6.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/docx-moderate-skipped-headings.docx` | H1 → H3 (skips H2), otherwise well-structured |
| `test-corpus/files/docx-clean-accessible.docx` | Full heading hierarchy, title set, lang set — should pass |
