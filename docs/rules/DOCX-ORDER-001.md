# DOCX-ORDER-001 — Floating text may disrupt reading order

**WCAG:** 1.3.2 Meaningful Sequence (Level A)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `api/office_structure.py`

## What it checks

Detects text boxes and other floating shapes have an undefined position in the document's reading order. screen readers may announce them out of sequence relative to surrounding paragraph text in docx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Meaningful Sequence (1.3.2) requires that reading order must be preserved so the content makes sense when linearised. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_docx_order_001_flags_violation(tmp_path):
    # Create a minimal docx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for docx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the docx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
