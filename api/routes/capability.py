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
    """The two-axis capability matrix (ADR 0023) + vocabularies + format order.

    `capability` is the single-value REMEDIATION projection (⚡ auto / 🤖 assisted / 👤 human),
    the shape the frontend mirror has always consumed. `assessment` is the ASSESSMENT axis
    (🟢 auto / 🟡 review / 🔴 human) — can ACP determine compliance, independent of how a
    failure is remediated. Any (fmt, sc) absent from a format's map is out of scope (grey ⚪
    N/A in the UI; "human" for remediation defaulting)."""
    return {"formats": list(cap.FORMATS),
            "lanes": sorted(cap.LANES),
            "capability": cap.remediation_table(),
            "assessment": cap.assessment_table(),
            "assessment_lanes": sorted(cap.ASSESSMENT_LANES)}
