# pdf.missing-alt-text — Image missing alt text

**WCAG:** 1.1.1 Non-text Content (Level A)  
**Severity:** CRITICAL  
**Fix mode:** auto  
**Source:** `worker-python/analysers/rules/pdf/alt_text.py`

## What it checks

Walks the PDF structure tree and finds every `<Figure>` tag. For each one, checks that the tag's `/Alt` attribute is present and non-empty. The check skips figures that are marked as Artifact (decorative) in the tag tree.

## Why it matters

PDF screen readers (Adobe Acrobat's built-in reader, NVDA with the PDF plugin) announce the `/Alt` value when the user navigates to a figure tag. Without it, the reader says nothing or reads the image stream's internal name.

## How the engine fixes it (auto)

For each untagged figure, the engine:
1. Extracts the image bytes from the PDF stream.
2. Sends them to the caption model (same pipeline as DOCX-ALT-001).
3. Sets the `/Alt` entry on the tag using `pypdf` or `pikepdf`.

The fix is applied to a copy; the original PDF is not modified in place.

## Unit test recipe

```python
import pypdf

def test_missing_alt_flagged(tmp_path):
    # Build a minimal PDF with a Figure tag and no /Alt
    pdf = _build_pdf_with_figure(alt=None)
    issues = run_rule(pdf)
    assert any(i.rule_id == "pdf.missing-alt-text" for i in issues)

def test_with_alt_passes(tmp_path):
    pdf = _build_pdf_with_figure(alt="Diagram showing network topology")
    issues = run_rule(pdf)
    assert not issues
```

## Failure modes

- **False negative:** scanned PDFs (image-only, no tag tree) have no `<Figure>` tags at all — `pdf.tagged` fires instead, and this rule finds nothing to check.
- **False positive:** none known in current implementation.
