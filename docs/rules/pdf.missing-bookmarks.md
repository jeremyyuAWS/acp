# pdf.missing-bookmarks — No navigation bookmarks

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** MINOR  
**Fix mode:** auto  
**Source:** `deploy/public/vendor/worker-python/analysers/rules/pdf/bookmarks.py`

## What it checks

Documents with more than one page must have an `/Outlines` tree containing at least one entry. NOT checked: outline depth/coverage, whether entries target valid destinations, or single-page documents (exempt).

## Why it matters

Bookmarks are the PDF's navigation panel — for a 40-page policy, the difference between jumping to "Appeals process" and paging through everything.

## Fix mode rationale

**auto** — the engine builds an outline from H1/H2 tags with page destinations. Additive: no page content changes.

## Unit test recipe

```python
import pikepdf
with pikepdf.open("pdf-clean-accessible.pdf") as pdf:
    outlines = pdf.Root.get("/Outlines")
    assert outlines is not None and outlines.get("/First") is not None
```

## Failure modes

- **False positive:** Short multi-page letters (2–3 pages) are flagged despite gaining little from an outline.
- **False negative:** An outline of one vague entry ("Document") satisfies the rule.
