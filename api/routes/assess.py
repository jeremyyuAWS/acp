"""Assess-lifecycle read-only preview endpoints (Phase C2, Discover/Assess PRD).

Before starting an assessment, a user picks a WCAG code-set (default = the canonical
Core 17) and sees how many discovered files are eligible for it. These endpoints answer
that from the latest discovery inventory.

READ-ONLY by construction: they never start a scan, and they never write to the store.
They read `scan_runs.scope.inventory` (the `estate_inventory.summarize()` snapshot the
last discovery run persisted) and project the Core-17 code-set over it.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

import core
import wcag_codeset

router = APIRouter()


def _owner(request: Request) -> str:
    """The current user for per-user data isolation — the gate-verified email, or
    'demo' for the keyless/demo path. Matches the owner stamped on scans at creation."""
    return getattr(request.state, "user_email", None) or "demo"


def _latest_inventory(owner: str) -> dict | None:
    """The estate inventory from this owner's most recent completed scan, or None.

    `list_scans` returns completed scans newest-first with `scope` already decoded to a
    dict, so the first row that carries an `inventory` block is the current estate. A
    read-only lookup — no scan is triggered if none exists; the caller renders zeros.
    """
    try:
        scans = core.store.list_scans(owner)
    except Exception:
        return None
    for s in scans:
        scope = s.get("scope")
        if isinstance(scope, dict) and isinstance(scope.get("inventory"), dict):
            return scope["inventory"]
    return None


@router.get("/assess/codeset")
def assess_codeset():
    """The Core-17 catalog a UI renders as the selectable code-set:
    `{"codes": [{code, name, formats:[...]}, ...]}`."""
    return {"codes": wcag_codeset.core17_catalog()}


@router.get("/assess/eligibility")
def assess_eligibility(request: Request, codes: str | None = Query(None)):
    """How many discovered files are eligible for the selected WCAG code-set.

    `codes` — optional comma-separated SC list (e.g. `1.4.3,2.4.6`); default = Core 17.
    Unknown / non-Core-17 tokens are ignored. Returns the eligible count, an eligible
    by-format breakdown, the eligible format set, the total discovered, and the selected
    codes with their per-code lanes + reach. Zeros (not a 500) when no discovery run
    exists yet. Never triggers a scan or mutates state.
    """
    selected = wcag_codeset.parse_codes(codes)
    inventory = _latest_inventory(_owner(request))
    return wcag_codeset.eligibility(inventory, selected)
