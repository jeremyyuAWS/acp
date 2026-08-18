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
import estate_inventory
import scope_resolver
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


def _latest_scan_id_with_inventory(owner: str) -> str | None:
    """The id of this owner's most recent completed scan that carries per-file inventory
    rows, or None. `list_scans` is newest-first, so the first scan whose `scan_inventory`
    is non-empty is the current per-file estate. Read-only; never triggers a scan."""
    try:
        scans = core.store.list_scans(owner)
    except Exception:
        return None
    for s in scans:
        sid = s.get("id")
        if not sid:
            continue
        try:
            if core.store.list_inventory(sid):
                return sid
        except Exception:
            continue
    return None


@router.get("/assess/eligibility/scoped")
def assess_eligibility_scoped(request: Request, codes: str | None = Query(None)):
    """Scope-aware eligibility: how many discovered files are eligible once enabled scope
    rules apply, per file.

    `codes` — optional comma-separated SC list; default = Core 17. This is the
    `default_codes` a file keeps when NO scope rule matches it. For each file in the latest
    discovery's per-file inventory we resolve its effective code-set from the enabled scope
    rules (folder / owner / department), then count it eligible when its format has an
    assessment lane for at least one code in that RESOLVED set.

    Returns `{discovered, eligible, by_format, rules_applied}`. Zeros (never a 500) when no
    discovery run exists yet. Reads only — starts no scan and mutates nothing.
    """
    default_codes = wcag_codeset.parse_codes(codes)
    owner = _owner(request)

    try:
        rules = core.store.list_scope_rules(enabled_only=True)
    except Exception:
        rules = []

    sid = _latest_scan_id_with_inventory(owner)
    if not sid:
        return {"discovered": 0, "eligible": 0, "by_format": {}, "rules_applied": 0}

    try:
        inventory = core.store.list_inventory(sid)
    except Exception:
        inventory = []

    discovered = len(inventory)
    by_format: dict[str, int] = {}
    matched_rule_ids: set = set()

    for row in inventory:
        file = {
            "path": row.get("path"),
            "parent_folder": row.get("parent_folder"),
            "owner": row.get("owner"),
        }
        resolved = scope_resolver.resolve(file, rules, default_codes)
        # Which enabled rules actually reach a file — reported as rules_applied.
        for r in rules:
            if scope_resolver.matches(file, r):
                matched_rule_ids.add(r.get("rule_id"))

        fmt = estate_inventory._format_of(row.get("file") or "", row.get("mime") or "")
        # Eligible iff the file's format has a lane for at least one resolved code. The
        # lane union for a code-set is drawn from the same Core-17 catalog the resolver
        # validated against, so image/av/other formats can never be counted eligible.
        if fmt in wcag_codeset.formats_for_codes(resolved):
            by_format[fmt] = by_format.get(fmt, 0) + 1

    return {
        "discovered": discovered,
        "eligible": sum(by_format.values()),
        "by_format": dict(sorted(by_format.items())),
        "rules_applied": len(matched_rule_ids),
    }
