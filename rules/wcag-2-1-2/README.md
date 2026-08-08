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
| `test-corpus/files/docx-noncompliant.docx` | no title/lang, missing alt, generic link, table w/o header — many SERIOUS/CRITICAL |
| `test-corpus/files/pptx-noncompliant.pptx` | no slide title, image w/o alt, no language (rule ids approximate) |
| `test-corpus/files/xlsx-noncompliant.xlsx` | no title/lang, generic 'Sheet' name, merged cells, hidden sheet (rule ids approximate) |
| `test-corpus/files/pdf-untagged.pdf` | untagged + no title + no /Lang (rule ids approximate) |
