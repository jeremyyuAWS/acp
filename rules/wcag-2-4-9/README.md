# WCAG 2.4.9 — Link Purpose (Link Only)

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.4.9 Link Purpose (Link Only) (Level AAA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-link-only.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### HTML engine (deterministic, in-app)

- Module: [`frontend/src/rules/wcag-2-4-9.js`](../../frontend/src/rules/wcag-2-4-9.js)
- Fix mode: `ai-assisted`
- Exports `check(doc)` and `fix(doc)` — see [frontend/src/rules/index.js](../../frontend/src/rules/index.js).

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `DOCX_LINK_PURPOSE_AMBIGUOUS` | docx | `api/office_structure.py:docx_checks` |
| `HTML_LINK_PURPOSE_AMBIGUOUS` | html | `api/scanner.py:_analyse_html` |
| `PPTX_LINK_PURPOSE_AMBIGUOUS` | pptx | `api/office_structure.py:pptx_checks` |

## How to change this rule

- **HTML:** edit [`frontend/src/rules/wcag-2-4-9.js`](../../frontend/src/rules/wcag-2-4-9.js). Change `check()` to alter detection, `fix()` to alter the deterministic remediation. The orchestrator picks it up automatically — no other file changes needed.
- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-critical-untagged-no-lang.pdf` | No tags, no title, no language, ambiguous link text — worst case |
| `test-corpus/files/docx-serious-ambiguous-links.docx` | Ambiguous link text (click here / read more), images without alt |
