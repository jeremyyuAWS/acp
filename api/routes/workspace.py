"""GET /workspace/bootstrap — one round trip for the first screen (workspace-bootstrap
redesign, Phase 1 step 1).

App.jsx's initial-load chain today makes four separate requests before Overview has
anything to show: GET /me, GET /scans (the picker list), GET /scans/{id} (the FULL scan
— every file, every finding, the exact payload Phase 1's snapshot cache exists to avoid
recomputing), and GET /scans/active. This endpoint answers the first three with one
request, substituting the cached Overview snapshot (api/store.py get_overview_snapshot)
for the full scan payload — a scan's files/findings are not needed to render the
Overview shell, only its aggregate counts.

/me itself (frontend/src/api.js) is intentionally NOT folded in here: it calls Google's
Drive About API for display name/photo, and duplicating a live external Drive call would
make this endpoint exactly the kind of expensive prerequisite it exists to avoid. The
identity fields returned below (email, is_scope_owner, is_admin) are the same ones
frontend already gets from `request.state.user_email` + core.is_scope_owner/is_admin —
no I/O, so folding them in costs nothing.

Out of scope for this endpoint (design doc steps 3+, tracked as follow-up, same as
Phase 1a/PR #960): response pagination, a full-payload ETag, lazy per-tab loading, and
perf-mark instrumentation. `revision` below is the scan's own cache-key revision number
— cheap to compare across polls — not a hash of this whole response.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

import core

router = APIRouter()


def _owner(request: Request) -> str:
    """The current user for per-user data isolation — the gate-verified email, or
    'demo' for the keyless/demo path. Matches the owner stamped on scans at creation."""
    return getattr(request.state, "user_email", None) or "demo"


# Mirrors frontend/src/defaultScan.js pickDefaultScan EXACTLY (same constants, same
# algorithm) so the scan this endpoint treats as "the" default is the one the SPA would
# already have picked itself from the identical `scans` list — ported, not shared,
# because the two run in different languages. tests/test_workspace_bootstrap.py pins
# this against the same cases frontend/src/defaultScan.test.js does, so the two cannot
# quietly drift apart.
_COLLAPSE_RATIO = 0.5
_COLLAPSE_WINDOW = 10


def _files(scan: dict) -> int:
    n = scan.get("files")
    return n if isinstance(n, (int, float)) else 0


def pick_default_scan(scans: list[dict], ratio: float = _COLLAPSE_RATIO,
                      window: int = _COLLAPSE_WINDOW) -> dict | None:
    """The newest scan in `scans` (already newest-first, as list_finished_scans returns
    them) that is NOT collapsed relative to its recent siblings, preferring a published
    scan among the survivors. See frontend/src/defaultScan.js for the full rationale —
    kept in lockstep with it, not just inspired by it."""
    if not scans:
        return None
    recent = scans[:window]
    biggest = max((_files(s) for s in recent), default=0)
    if not biggest:
        return scans[0]                                    # nothing to compare on — keep newest
    floor = biggest * ratio
    above_floor = [s for s in recent if _files(s) >= floor]
    if not above_floor:
        return scans[0]
    return next((s for s in above_floor if s.get("published_at")), above_floor[0])


@router.get("/workspace/bootstrap")
def bootstrap(request: Request):
    """Identity/permissions, the recent scan-picker list, the default scan's cached
    Overview snapshot, and the active-job summary — everything Overview needs to render
    a meaningful shell, in one request."""
    owner = _owner(request)
    scans = core.store.list_finished_scans(owner=owner)
    default = pick_default_scan(scans)

    overview = None
    scan_id = scan_status = revision = None
    if default and default.get("id"):
        scan_id = default["id"]
        head = core.store.get_scan_head(scan_id, owner=owner)
        if head:                    # should always hit — `default` just came from this owner's list
            scan_status = head["status"]
            revision = head["revision"]
        overview = core.store.get_overview_snapshot(scan_id, owner)

    return {
        "me": {
            "email": owner,
            "is_scope_owner": core.is_scope_owner(owner),
            "is_admin": core.is_admin(owner),
        },
        "scan_id": scan_id,
        "scan_status": scan_status,
        "revision": revision,
        "overview": overview,
        "scans": scans,
        "active_job": core.store.active_scan(owner=owner) or {},
    }
