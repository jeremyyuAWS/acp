# PPTX-KBTRAP-001 — Embedded control may trap keyboard focus

**WCAG:** 2.1.2 No Keyboard Trap (Level A)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `api/office_structure.py`

## What it checks

Detects the presentation contains an embedded control (activex, ole object) that may not allow keyboard focus to move away. verify the user can leave the control using tab or escape in pptx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

No Keyboard Trap (2.1.2) requires that keyboard focus must never be trapped inside a component. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pptx_kbtrap_001_flags_violation(tmp_path):
    # Create a minimal pptx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pptx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pptx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
