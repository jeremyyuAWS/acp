# WCAG 3.1.4 — Abbreviations

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 3.1.4 Abbreviations (Level AAA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/abbreviations.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-3-1-4.js`](../../frontend/src/rules/wcag-3-1-4.js)
- Fix mode: `auto`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-3-1-4.js`](../../frontend/src/rules/wcag-3-1-4.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-moderate-mixed.pdf` | Has title but missing lang, abbreviations unexplained |
