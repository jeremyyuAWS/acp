# pdf.display-doc-title — Viewer not set to show title

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `deploy/public/vendor/worker-python/analysers/rules/pdf/display_title.py`

## What it checks

`/ViewerPreferences << /DisplayDocTitle true >>` in the catalog. NOT checked: whether a title exists to display — that is `pdf.document-title`; both must pass for the pair to work.

## Why it matters

With the flag off, PDF viewers put the FILENAME in the window title, so even a perfect `/Title` never reaches the screen reader's window announcement. It's the cheapest fix in the whole catalog and one of the most commonly missed (it's a PDF/UA hard requirement).

## Fix mode rationale

**auto** — a single boolean write on the catalog's viewer preferences.

## Unit test recipe

```python
import pikepdf
with pikepdf.open("pdf-clean-accessible.pdf") as pdf:
    vp = pdf.Root.get("/ViewerPreferences", {})
    assert bool(vp.get("/DisplayDocTitle", False))
```

## Failure modes

- **False positive:** None — the check is a boolean read.
- **False negative:** None — the check is exhaustive for what it claims.
