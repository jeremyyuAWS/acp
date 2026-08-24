"""Cross-scan analytics — the estate's trajectory over time, not one scan's snapshot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


@router.get("/admin/analytics/overview")
def admin_analytics_overview(
    request: Request,
    period: str = Query("30d", pattern="^(today|7d|30d|90d|all)$"),
    source: str | None = Query(None),
):
    """Admin-only estate analytics overview across ALL users.

    Returns KPI cards (total docs, certifiable rate, avg score, scan count), a by-source
    breakdown, and a compliance trend series for the chosen period. Backend-enforced:
    _require_admin raises 403 for any non-admin caller regardless of what the UI shows.

    period: today | 7d | 30d | 90d | all (default: 30d)
    source: drive | sharepoint | local — narrows to one connector, or all when omitted.
    """
    from .system import _require_admin
    _require_admin(request)

    all_scans = core.store.list_scans_admin()

    # Period cutoff — completed_at is stored as an ISO string; compare as string prefix (YYYY-MM-DD)
    # which sorts correctly. Use UTC so the server timezone never shifts the boundary.
    now = datetime.now(tz=timezone.utc)
    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()[:10]
    elif period == "7d":
        cutoff = (now - timedelta(days=7)).isoformat()[:10]
    elif period == "30d":
        cutoff = (now - timedelta(days=30)).isoformat()[:10]
    elif period == "90d":
        cutoff = (now - timedelta(days=90)).isoformat()[:10]
    else:
        cutoff = None

    scans = all_scans
    if cutoff:
        scans = [s for s in scans if (s.get("completed_at") or "") >= cutoff]
    if source:
        scans = [s for s in scans if s.get("source") == source]

    total_docs = sum(s.get("files") or 0 for s in scans)
    total_cert = sum(s.get("certifiable") or 0 for s in scans)
    scores = [s["avg_score"] for s in scans if s.get("avg_score") is not None]

    # Per-source breakdown: scan count, doc count, certifiable count
    by_source: dict = {}
    for s in scans:
        src = s.get("source") or "unknown"
        b = by_source.setdefault(src, {"scans": 0, "docs": 0, "certifiable": 0})
        b["scans"] += 1
        b["docs"] += s.get("files") or 0
        b["certifiable"] += s.get("certifiable") or 0

    # Recent scans — newest first, cap at 20 for the dashboard table
    recent = [
        {
            "id": s.get("id"),
            "completed_at": s.get("completed_at"),
            "source": s.get("source"),
            "files": s.get("files"),
            "certifiable": s.get("certifiable"),
            "avg_score": s.get("avg_score"),
            "owner_email": s.get("owner_email"),
        }
        for s in scans[:20]
    ]

    return {
        "period": period,
        "source": source,
        "scans": len(scans),
        "docs": total_docs,
        "certifiable": total_cert,
        "certifiable_rate": round(total_cert / total_docs * 100, 1) if total_docs else None,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "by_source": by_source,
        "trend": analytics_trends.compliance_trend(scans),
        "recent_scans": recent,
    }
