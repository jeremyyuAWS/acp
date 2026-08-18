"""Cross-scan analytics — the estate's trajectory over time, not one scan's snapshot."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

import analytics_trends
import core

router = APIRouter()


def _owner(request: Request) -> str:
    # Same per-user isolation the scan routes use: a user's trend is built only from their own scans.
    return getattr(request.state, "user_email", None) or "demo"


@router.get("/analytics/compliance-trend")
def compliance_trend(request: Request, source: str | None = Query(None)):
    """The signed-in user's compliance trajectory across their completed scans — a chronological
    score series plus a summary (first vs latest, the delta, and its direction).

    Owner-scoped via list_scans, so it never mixes one user's estate into another's. `source`
    (drive | sharepoint | local) narrows the trend to a single connector when given — the estate
    trajectory for that source alone — otherwise every source counts.
    """
    scans = core.store.list_scans(owner=_owner(request))
    if source:
        scans = [s for s in scans if s.get("source") == source]
    return analytics_trends.compliance_trend(scans)
