# WCAG 2.1.2 — No Keyboard Trap

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 2.1.2 No Keyboard Trap (Level A)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/no-keyboard-trap.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `OFFICE_INTERACTIVE_CONTROL_KEYBOARD` | docx, pptx, xlsx | `api/office_structure.py:office_control_review_checks` |

## How to change this rule

- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/pdf-critical-untagged-no-lang.pdf` | No tags, no title, no language, ambiguous link text — worst case |
| `test-corpus/files/docx-critical-no-headings.docx` | Bold-as-heading, low-contrast text, pseudo-bullets, no title |
| `test-corpus/files/pptx-critical-no-titles.pptx` | Blank layout slides, no slide titles, low contrast, no semantic structure |
| `test-corpus/files/pdf-serious-contrast.pdf` | Nearly-invisible light-grey text on white, no language |
| `test-corpus/files/pptx-moderate-title-only.pptx` | Has slide titles but no content placeholders, pseudo-bullets in textbox |
| `test-corpus/files/pdf-clean-accessible.pdf` | Title set, black text, no structural issues — should score 100 |
