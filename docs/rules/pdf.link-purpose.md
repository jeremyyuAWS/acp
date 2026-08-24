# pdf.link-purpose — Link text is a raw URL

**WCAG:** 2.4.4 Link Purpose (In Context) (Level A)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `api/office_structure.py`

## What it checks

Detects a hyperlink's visible text is the raw url rather than a description of the destination. screen reader users who navigate by links cannot determine the purpose of a raw url link out of context in pdf documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Link Purpose (In Context) (2.4.4) requires that link purpose must be determinable from the link text or its context. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pdf_link_purpose_flags_violation(tmp_path):
    # Create a minimal pdf document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pdf.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pdf XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
