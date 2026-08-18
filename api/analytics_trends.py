"""Compliance-trend-over-time analytics (audit gap A2).

Every completed scan already persists its headline facts — `completed_at`, `avg_score`, `files`,
`certifiable` — so the estate's compliance trajectory is latent in the scan history and needs no new
capture. The dashboard could show a score today but not whether it is rising or falling; a pilot
that cannot show movement cannot show the platform is working.

This module turns the scan history (as `store.list_scans` returns it) into a chronological series
plus a compact summary — first vs latest score, the delta, and its direction. Deliberately standalone
(no store / no FastAPI import) so the trajectory math is a single authority and unit-testable without
a database: the route hands it `list_scans(owner)` and returns the result.
"""
from __future__ import annotations

from datetime import datetime

# A score change smaller than this is reported "flat" rather than as a direction. Half a point of
# a 0–100 score is noise (one borderline finding on one file), and calling noise "improving" or
# "declining" is the failure a trend indicator most easily commits.
_FLAT_BAND = 0.5


def _parse(ts) -> datetime | None:
    """Parse an ISO-8601 timestamp (with or without a trailing 'Z') to a datetime, or None. A point
    the platform cannot place in time cannot sit on a trend line, so it is dropped rather than guessed."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(v):
    """A finite number, or None. Guards the None counters a cancelled/interrupted scan leaves behind
    (see store._fill_run_aggregate) from being treated as a real 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _point(scan: dict) -> dict | None:
    """One trend point from a list_scans row, or None when it has no place in time. `score` is None
    for a scan that never produced one (cancelled mid-run); the point is still emitted so the file
    count is not lost, and the score series simply skips it."""
    at = _parse(scan.get("completed_at"))
    if at is None:
        return None
    files = _num(scan.get("files"))
    certifiable = _num(scan.get("certifiable"))
    score = _num(scan.get("avg_score"))
    pct = round(certifiable / files * 100, 1) if (files and certifiable is not None) else None
    return {
        "scan_id": scan.get("id"),
        "at": scan.get("completed_at"),
        "_at": at,                                   # parsed, for sorting only — stripped before return
        "source": scan.get("source"),
        "score": score,
        "files": int(files) if files is not None else None,
        "certifiable": int(certifiable) if certifiable is not None else None,
        "certifiable_pct": pct,
    }


def _summary_of(points: list[dict]) -> dict:
    """The first-vs-latest movement summary for an already-chronological list of trend points.

    Shared by the overall trend and each per-source trend so the two can never disagree on what
    'improving' means. `points` must already be sorted oldest → newest.
    """
    scored = [p for p in points if p["score"] is not None]
    summary: dict = {
        "n": len(points), "scored": len(scored),
        "first": None, "latest": None, "delta": None,
        "direction": "insufficient", "best": None, "span_days": None,
    }
    if points:
        summary["span_days"] = (_parse(points[-1]["at"]) - _parse(points[0]["at"])).days
    if scored:
        summary["best"] = max(p["score"] for p in scored)
    if len(scored) >= 2:
        first, latest = scored[0]["score"], scored[-1]["score"]
        delta = round(latest - first, 1)
        summary.update({
            "first": first, "latest": latest, "delta": delta,
            "direction": ("improving" if delta > _FLAT_BAND
                          else "declining" if delta < -_FLAT_BAND else "flat"),
        })
    elif len(scored) == 1:
        # One scored scan is a baseline, not a trend: report the value as both ends but claim no
        # movement. Saying "improving" off a single point is the trend indicator's cardinal lie.
        only = scored[0]["score"]
        summary.update({"first": only, "latest": only, "delta": None, "direction": "insufficient"})
    return summary


def compliance_trend(scans: list[dict] | None) -> dict:
    """The estate's compliance trajectory from its scan history.

    `scans` is `store.list_scans(owner)` output (any order; that method returns newest-first). Returns
    `points` in CHRONOLOGICAL order (oldest → newest) for a line chart, and a `summary`:

      * n                — points placed in time
      * scored           — points that carried a score (the trend line's real length)
      * first / latest   — the oldest and newest SCORED values, the endpoints of the movement
      * delta            — latest − first, the headline "are we improving" number (None if < 2 scored)
      * direction        — improving | declining | flat (within a half-point band) | insufficient
      * best             — the highest score reached, so a regression from a past peak is visible
      * span_days        — calendar days from first to last point

    `by_source` carries the SAME summary shape per connector (drive / sharepoint / local), so a
    multi-source estate can see which source is improving and which is lagging rather than only the
    blended figure — the blend can hide a declining SharePoint behind a rising Drive. Keyed by the
    source string, sources in first-seen chronological order.

    Every number is COUNTED from stored rows; none is estimated. An empty or single-scan history
    returns a well-formed summary with direction 'insufficient', never a fabricated slope.
    """
    points = [p for p in (_point(s) for s in (scans or [])) if p is not None]
    points.sort(key=lambda p: p["_at"])
    for p in points:
        p.pop("_at", None)

    # Per-source trends, sources in first-seen order (points are already chronological). A None
    # source is bucketed under "unknown" rather than dropped — a scan with no recorded source still
    # happened and still moved the blended number.
    by_source: dict = {}
    order: list = []
    for p in points:
        src = p.get("source") or "unknown"
        if src not in by_source:
            by_source[src] = []
            order.append(src)
        by_source[src].append(p)

    return {
        "points": points,
        "summary": _summary_of(points),
        "by_source": {src: _summary_of(by_source[src]) for src in order},
    }
