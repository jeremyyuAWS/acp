# pdf.form-field-name — Form field has no accessible name

**WCAG:** 4.1.2 Name, Role, Value (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `api/formats/pdf/detectors/name_role_value.py`

## What it checks

Detects an acroform terminal field's /tu (tooltip / accessible name) entry is absent or generic. screen readers announce /tu when focus reaches the field. the engine copies a meaningful /t value into /tu where available in pdf documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Name, Role, Value (4.1.2) requires that all interactive components must expose name, role, and value to the accessibility tree. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pdf_form_field_name_flags_violation(tmp_path):
    # Create a minimal pdf document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pdf.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pdf XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
