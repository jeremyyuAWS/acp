# pdf.headings-labels — Tagged PDF has no heading structure

**WCAG:** 2.4.6 Headings and Labels (Level AA)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `api/office_structure.py`

## What it checks

Detects a tagged pdf with no heading tags (h1–h6) provides no navigable structure. screen reader users who jump by heading cannot skim the document. the engine proposes a heading map derived from font-size hierarchy for human confirmation in pdf documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Headings and Labels (2.4.6) requires that headings and labels must describe their topic or purpose. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pdf_headings_labels_flags_violation(tmp_path):
    # Create a minimal pdf document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pdf.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pdf XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
