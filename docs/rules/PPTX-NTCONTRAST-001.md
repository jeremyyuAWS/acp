# PPTX-NTCONTRAST-001 — Non-text element has insufficient contrast

**WCAG:** 1.4.11 Non-text Contrast (Level AA)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `api/office_structure.py`

## What it checks

Detects a shape border or informational graphic has a contrast ratio below 3:1 against its background. ui components and graphics that convey meaning must meet this threshold for low-vision users in pptx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Non-text Contrast (1.4.11) requires that non-text UI components and graphical objects must meet a 3:1 contrast ratio against adjacent colours. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pptx_ntcontrast_001_flags_violation(tmp_path):
    # Create a minimal pptx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pptx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pptx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
