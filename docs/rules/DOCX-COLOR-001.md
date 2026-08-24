# DOCX-COLOR-001 — Information conveyed by colour alone

**WCAG:** 1.4.1 Use of Color (Level A)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `api/office_structure.py`

## What it checks

Detects hyperlinks with underlines removed rely on colour as the sole visual cue. users who cannot distinguish colours will miss the link indicator. restore the underline or add another non-colour cue in docx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Use of Color (1.4.1) requires that colour must not be the only way to convey information. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_docx_color_001_flags_violation(tmp_path):
    # Create a minimal docx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for docx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the docx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
