# WCAG 1.4.5 — Images of Text

> **GENERATED FILE.** Edit the sources (rule-catalog.json, frontend/src/rules/, api/office_structure.py, api/textchecks.py, api/ocr.py, test-corpus/manifest.json), then run `python scripts/gen_rules_index.py`. Do not hand-edit.

- **Success Criterion:** 1.4.5 Images of Text (Level AA)
- **Understanding doc:** https://www.w3.org/WAI/WCAG21/Understanding/images-of-text.html
- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)

## Where this is checked

### First-party checks (Python, in-repo)

| Rule ID | Formats | Source |
|---------|---------|--------|
| `OCR_IMAGE_OF_TEXT` | docx, pdf, pptx, xlsx | `api/ocr.py` |
| `PDF_LIKELY_SCANNED` | pdf | `api/office_structure.py:pdf_scanned_page_checks` |

## How to change this rule

- **First-party Python:** edit the `source` function above. These run in-process on top of the engine result (`api/scanner.py`), and `office_structure.checks_for()` decides which formats each one reaches — add a check there or it will never be dispatched.

## Test fixtures

| File | What it exercises |
|------|-------------------|
| `test-corpus/files/docx-serious-ambiguous-links.docx` | Ambiguous link text (click here / read more), images without alt |
