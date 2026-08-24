# PPTX-REFLOW-001 — Wide table may not reflow at narrow viewport

**WCAG:** 1.4.10 Reflow (Level AA)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `api/office_structure.py`

## What it checks

Detects a table wider than the slide content area may require two-dimensional scrolling when the presentation is viewed at 320 css pixels. prefer narrower tables or portrait layouts that reflow to one column in pptx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Reflow (1.4.10) requires that content must reflow to a single column at 320 CSS px width without horizontal scrolling. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pptx_reflow_001_flags_violation(tmp_path):
    # Create a minimal pptx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pptx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pptx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
