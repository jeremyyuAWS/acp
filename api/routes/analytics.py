"""Cross-scan analytics — the estate's trajectory over time, not one scan's snapshot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
import analytics_overview

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
    response: Response,
    period: str = Query("30d", pattern="^(today|7d|30d|90d|all|custom)$"),
    source: str | None = Query(None),
    owner: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    start: str | None = Query(None),
    end: str | None = Query(None),
    timezone_name: str = Query("UTC", alias="timezone"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
    response.headers["Cache-Control"] = "no-store"

    activity = analytics_overview.build(core.store.list_scan_attempts_admin(), period=period,
        source=source, owner=owner, status=status, search=search, start=start, end=end,
        timezone_name=timezone_name, page=page, page_size=page_size)
    all_scans = core.store.list_scans_admin()

    lower = analytics_overview.timestamp(activity["reporting"]["start"])
    upper = analytics_overview.timestamp(activity["reporting"]["end"])
    scans = analytics_overview.filtered(all_scans, source, owner, status, search)
    scans = [s for s in scans if analytics_overview.within(s.get("completed_at"), lower, upper)]

    total_docs = sum(s.get("files") or 0 for s in scans)
    total_cert = sum(s.get("certifiable") or 0 for s in scans)
    total_uncertain = sum(s.get("uncertain") or 0 for s in scans)
    total_error_docs = sum(s.get("error") or 0 for s in scans)
    scan_exceptions = sum(1 for s in scans if (s.get("error") or 0) > 0)
    scores = [s["avg_score"] for s in scans if s.get("avg_score") is not None]

    # Per-source breakdown: scan count, doc count, certifiable count, uncertain, errors
    by_source: dict = {}
    for s in scans:
        src = s.get("source") or "unknown"
        b = by_source.setdefault(src, {"scans": 0, "docs": 0, "certifiable": 0, "uncertain": 0, "error_docs": 0})
        b["scans"] += 1
        b["docs"] += s.get("files") or 0
        b["certifiable"] += s.get("certifiable") or 0
        b["uncertain"] += s.get("uncertain") or 0
        b["error_docs"] += s.get("error") or 0

    # Pending HITL review items
    try:
        review_pending = len(core.store.list_hitl_queue(status="pending"))
    except Exception:
        review_pending = None

    # Recent scans — newest first, cap at 20 for the dashboard table. `status` rides along so the
    # UI can tell a real zero (assessed, nothing eligible) apart from a scan that never reached
    # assessment at all (cancelled by the user, or interrupted mid-run) — both leave files/
    # certifiable at 0/NULL, and without the status a viewer can't tell which happened.
    recent = [
        {
            "id": s.get("id"),
            "completed_at": s.get("completed_at"),
            "source": s.get("source"),
            "files": s.get("files"),
            "certifiable": s.get("certifiable"),
            "uncertain": s.get("uncertain"),
            "avg_score": s.get("avg_score"),
            "status": s.get("status"),
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
        "uncertain": total_uncertain,
        "error_docs": total_error_docs,
        "scan_exceptions": scan_exceptions,
        "review_pending": review_pending,
        "certifiable_rate": round(total_cert / total_docs * 100, 1) if total_docs else None,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "by_source": by_source,
        "trend": analytics_trends.compliance_trend(scans),
        "recent_scans": recent,
        **activity,
    }


@router.get("/admin/analytics/scans/{scan_id}")
def admin_analytics_detail(request: Request, scan_id: str, response: Response):
    from .system import _require_admin
    _require_admin(request)
    response.headers["Cache-Control"] = "no-store"
    row = core.store.get_scan_attempt_admin(scan_id)
    if row is None:
        raise HTTPException(404, "Scan not found")
    scan = core.store.get_scan(scan_id)
    return {"scan": row, "observations": (scan or {}).get("files", []),
            "events": core.store.list_scan_events(scan_id, limit=100),
            "reporting": {"scope": "Platform · all users", "events_limit": 100,
                          "events_note": "First 100 recorded events; historical coverage may be incomplete"}}


@router.get("/admin/analytics/methodology")
def admin_analytics_methodology(request: Request, response: Response, basis: Literal["attempts", "results"] = "attempts", period: str = Query("30d", pattern="^(today|7d|30d|90d|all|custom)$"),
        source: str | None = None, owner: str | None = None, status: str | None = None,
        search: str | None = Query(None, max_length=200), start: str | None = None, end: str | None = None,
        timezone_name: str = Query("UTC", alias="timezone")):
    from .system import _require_admin
    _require_admin(request)
    response.headers["Cache-Control"] = "no-store"
    reporting = analytics_overview.build(core.store.list_scan_attempts_admin(), period=period, source=source,
        owner=owner, status=status, search=search, start=start, end=end, timezone_name=timezone_name)["reporting"]
    reporting["export_basis"] = basis
    reporting["time_basis"] = "completed_at (successful results)" if basis == "results" else "started_at (all recorded attempts)"
    return reporting


@router.get("/admin/analytics/export")
def admin_analytics_export(request: Request, basis: Literal["attempts", "results"] = "attempts", period: str = Query("30d", pattern="^(today|7d|30d|90d|all|custom)$"),
        source: str | None = None, owner: str | None = None, status: str | None = None,
        search: str | None = Query(None, max_length=200), start: str | None = None, end: str | None = None,
        timezone_name: str = Query("UTC", alias="timezone")):
    from .system import _require_admin
    _require_admin(request)
    import csv
    import io
    rows = core.store.list_scan_attempts_admin()
    data = analytics_overview.build(rows, period=period, source=source, owner=owner, status=status,
        search=search, start=start, end=end, timezone_name=timezone_name, page_size=max(len(rows), 1))
    register = data["results_register"] if basis == "results" else data["register"]
    output = io.StringIO()
    fields = ["id", "owner_email", "source", "started_at", "completed_at", "status", "files", "certifiable", "uncertain", "error", "avg_score", "rubric_name", "rubric_hash"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in register["rows"]:
        # Spreadsheet formula execution is not an intended interpretation of recorded metadata.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for k, v in row.items()})
    import json
    core.store.log_decision(_owner(request), "admin.analytics.export", detail=json.dumps({
        "scope": "platform-all-users", "filters": data["reporting"]["filters"],
        "start": data["reporting"]["start"], "end": data["reporting"]["end"],
        "rows": register["total"], "basis": basis, "generated_at": data["reporting"]["generated_at"], "outcome": "generated"}))
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="scan-analytics.csv"',
        "Cache-Control": "no-store", "X-Analytics-Scope": "platform-all-users", "X-Export-Rows": str(register["total"]), "X-Export-Basis": basis,
        "X-Analytics-Generated-At": data["reporting"]["generated_at"]})
