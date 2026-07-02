# pdf.document-title — Document title not set

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `deploy/public/vendor/worker-python/analysers/rules/pdf/document_title.py`

## What it checks

A non-empty `/Title` in the `/Info` dictionary or `dc:title` in XMP metadata (either satisfies). NOT checked: title quality, or whether the viewer is configured to *display* it — that is `pdf.display-doc-title`.

## Why it matters

The announced identity of the file. PDFs exported from scanners and print drivers routinely carry titles like "Microsoft Word - final_v3.docx", or nothing.

## Fix mode rationale

**auto** — the engine writes a title derived from the first H1 tag (or first text line) into both `/Info` and XMP.

## Unit test recipe

```python
import pikepdf
with pikepdf.open("pdf-titled-lang.pdf") as pdf:
    assert str(pdf.docinfo.get("/Title", "")).strip()
with pikepdf.open("pdf-untagged.pdf") as pdf:
    assert not str(pdf.docinfo.get("/Title", "")).strip()
```

## Failure modes

- **False positive:** None significant — presence is cheap to detect.
- **False negative:** Producer-artifact titles ("untitled", the source filename) pass.
