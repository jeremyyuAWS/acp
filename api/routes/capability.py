"""Read-only remediation-capability matrix.

Serves api/remediation_capability.CAPABILITY so the SPA can render "how is each finding
actioned?" (auto / assisted / human) straight from the single source of truth the contract
test (tests/test_remediation_capability.py) proves against the real remediators — no second,
drifting copy in the frontend. Static, non-sensitive product metadata; public like /config.
"""
from __future__ import annotations

from fastapi import APIRouter

import remediation_capability as cap

router = APIRouter()


@router.get("/capability")
def capability():
    """The full {format: {WCAG SC: lane}} matrix, the lane vocabulary, and the format order.

    `formats` + `capability` match the shape the frontend capability mirror consumes; `lanes`
    is the vocabulary. Any (fmt, sc) absent from a format's map is "human" (out of scope /
    no automation)."""
    return {"formats": list(cap.FORMATS), "lanes": sorted(cap.LANES),
            "capability": cap.as_dict()}
