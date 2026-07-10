"""Remediation-capability endpoint.

Read-only. Serves the single per-(criterion × format) automation table
(api/remediation_capability.py) so the frontend Assess + FileDrawer views consume
ONE authoritative answer to "which WCAG criterion can be auto-fixed on this format",
instead of the three hand-maintained tables that used to disagree.
"""
from __future__ import annotations

from fastapi import APIRouter

import remediation_capability as cap

router = APIRouter()


@router.get("/capability")
def capability():
    """The per-format remediation capability: {fmt: {sc: "auto"|"assisted"|"human"}}.
    Any (fmt, sc) absent from a format's map is "human" (no automation)."""
    return {"formats": list(cap.FORMATS), "capability": cap.as_dict()}
