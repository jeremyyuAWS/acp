# pdf.low-contrast — Insufficient colour contrast

**WCAG:** 1.4.3 Contrast (Minimum) (Level AA)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `api/office_structure.py`

## What it checks

Detects text fill colours in content streams must meet the 4.5:1 minimum contrast ratio against the resolved background for normal-sized text. the engine recolours failing text where the background can be structurally resolved in pdf documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Contrast (Minimum) (1.4.3) requires that text and images of text must meet a 4.5:1 contrast ratio (3:1 for large text). When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pdf_low_contrast_flags_violation(tmp_path):
    # Create a minimal pdf document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pdf.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pdf XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
