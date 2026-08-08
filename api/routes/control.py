"""The control plane — the estate, aggregated, for one tenant.

"Filter by dept, user, Enterprise" from the v2 requirements. The data was always there:
`documents` carries department and owner, and #159 gave it its own tenant column so a filter
built on it can be scoped without borrowing a column that means something else.

WHY THE OWNER COMES FROM THE REQUEST, NEVER FROM A QUERY PARAM. `?owner_email=` would be a
tenant selector any caller could set, which is not a filter — it is the absence of isolation
wearing a filter's clothes. The `dept` and `owner` parameters below ARE filters: they narrow
within the caller's own estate and cannot widen past it, because the tenant is applied first and
separately by the store (`estate_by_department`'s docstring is explicit that owner_email is
required precisely so it cannot be forgotten).

The store excludes NULL-tenant rows rather than treating them as a wildcard, so an estate scanned
before #159 reports as empty here until it is backfilled. That is the intended direction: a
document nobody sees is recoverable, a document the wrong customer sees is not.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import core

router = APIRouter()


def _owner(request: Request) -> str:
    """Same helper as routes/scans.py, and deliberately the same value: the estate a person sees
    here must be the estate their scans wrote. Two different notions of "who is asking" across
    two routes is how one of them quietly stops matching."""
    return getattr(request.state, "user_email", None) or "demo"


@router.get("/control/estate")
def estate(request: Request, dept: str = "", owner: str = ""):
    """Documents per department for the caller's tenant, with an owner breakdown alongside.

    `dept` and `owner` narrow WITHIN the tenant. Empty means no narrowing — not "all tenants".
    """
    who = _owner(request)
    try:
        by_dept = core.store.estate_by_department(who, department=dept or None, owner=owner or None)
        owners = core.store.estate_owners(who)
    except Exception as e:  # noqa: BLE001 — a query failure is the caller's to see, not a 500 log
        raise HTTPException(502, f"estate query failed: {e}") from e

    total = sum(r["documents"] for r in by_dept)
    return {
        "tenant": who,
        "departments": by_dept,
        "owners": owners,
        "documents": total,
        # Stated, not implied. Every screen in this product that shows a total is expected to say
        # what the total counts (see ScopeBanner, #164), and a JSON surface is read by the same
        # people. `filtered` distinguishes "your estate is empty" from "your filter matched
        # nothing" — two very different things that look identical as a zero.
        "filters": {"department": dept or None, "owner": owner or None},
        "filtered": bool(dept or owner),
    }
