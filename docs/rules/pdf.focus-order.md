# pdf.focus-order — Tab order not set to structure order

**WCAG:** 2.4.3 Focus Order (Level A)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `api/formats/pdf/detectors/focus_order.py`

## What it checks

Detects pages containing acroform widgets must set /tabs = /s in their page dictionary so the pdf viewer follows structure order when tab is pressed. without this, keyboard navigation order is undefined in pdf documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Focus Order (2.4.3) requires that focus order must preserve meaning and operability. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pdf_focus_order_flags_violation(tmp_path):
    # Create a minimal pdf document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pdf.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pdf XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
