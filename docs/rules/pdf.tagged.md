# pdf.tagged — PDF is not tagged

**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `worker-python/analysers/rules/pdf/tagged.py`

## What it checks

Checks two things:

1. The document catalog's `/MarkInfo` dictionary has `Marked = true`.
2. The document has a `/StructTreeRoot` — i.e. an actual structure (tag) tree exists and is non-empty.

A PDF that passes (1) but fails (2) is declared tagged but has no structure — this is a defective tag implementation and the rule still fires.

## Why it matters

The tag tree is the accessibility backbone of a PDF. Every other PDF rule (`pdf.missing-alt-text`, `pdf.reading-order`) depends on it. A PDF with no tag tree is inaccessible to screen readers regardless of any other metadata.

## Why fix mode is human-only

Adding a complete, semantically correct tag tree to an existing PDF requires understanding the document's visual layout and logical reading order — decisions that cannot be made automatically without high risk of errors. The correct fix is to regenerate the PDF from source (Word, InDesign, LaTeX) with tag export enabled.

## Failure modes

- **False negative:** some PDFs mark `Marked=true` in MarkInfo but have a stub StructTreeRoot with no children. The rule checks for a non-empty tree to catch this.
