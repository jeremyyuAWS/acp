"""Pure source-staleness classification for the Release Center's /source-status endpoint.

Kept free of Drive and the DB so the decision logic is unit-testable: given the source's
modifiedTime captured at scan time (the baseline) and its CURRENT modifiedTime, is the source
newer than the scan? Everything that isn't a timestamp comparison — no baseline, no Drive id, a
scan whose source isn't Drive, a Drive fetch that failed — is classified here too, from inputs
the endpoint passes in, so the endpoint stays a thin adapter.

States: 'stale' (source changed since the scan), 'unchanged', 'untracked' (nothing to compare —
never a false 'unchanged'), 'unavailable' (the source couldn't be read, or a timestamp wouldn't
parse). See classify_sync_state below for the fuller PRD Phase 3 vocabulary that layers ACP's
own import/publish state on top of these four.
"""
from __future__ import annotations

from datetime import datetime, timezone


def parse_rfc3339(s):
    """Parse a Drive modifiedTime ('2026-08-01T09:00:00.000Z', or without milliseconds) to an
    aware datetime, or None if it isn't a parseable timestamp."""
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compare_state(baseline, current):
    """'stale' if the source's current modifiedTime is strictly NEWER than the scan-time baseline,
    'unchanged' if equal or older. None when either value can't be parsed — the caller must treat
    that as unknown, never a false 'unchanged'. Compares aware datetimes, not raw strings, so a
    difference in millisecond precision between the two Drive responses can't fake a change."""
    b, c = parse_rfc3339(baseline), parse_rfc3339(current)
    if b is None or c is None:
        return None
    return "stale" if c > b else "unchanged"


def classify_file(file_row, current, *, source_is_drive, fetch_error=None):
    """Classify one file for the /source-status response.

    file_row      — the get_scan file dict (uses 'source_modified' + 'drive_file_id').
    current       — the source's current modifiedTime (str) or None.
    source_is_drive — whether the scan's source is Drive at all (SharePoint/local can't be checked).
    fetch_error   — a short code when the Drive read failed ('not_found' / 'forbidden' / 'drive_error').
    """
    baseline = (file_row or {}).get("source_modified")
    drive_id = (file_row or {}).get("drive_file_id")
    if not source_is_drive or not drive_id or not baseline:
        return {"state": "untracked", "baseline": baseline, "current": None}
    if fetch_error:
        return {"state": "unavailable", "baseline": baseline, "current": None, "error": fetch_error}
    st = compare_state(baseline, current)
    if st is None:
        return {"state": "unavailable", "baseline": baseline, "current": current, "error": "unparseable"}
    return {"state": st, "baseline": baseline, "current": current}


# --- PRD Phase 3: the fuller sync-state vocabulary ------------------------------------------
#
# classify_file above answers one question — has the SOURCE changed — from ACP's read-only view
# of it. The PRD asks for ACP's OWN side of the round trip too: is a file still being imported,
# did the import fail, does ACP hold a fix the source doesn't reflect, and do the two sides
# actively disagree. classify_sync_state layers that on top, so every existing classify_file
# caller (Release Center, Monitor) is untouched and every new caller gets the fuller vocabulary
# from one function.

def classify_sync_state(file_row, current, *, source_is_drive, fetch_error=None, run_status=None):
    """The fuller PRD Phase 3 vocabulary. A file is EXACTLY ONE of, checked in this order:

      'importing'       — the scan is still running and this file has not been analysed yet.
      'import_failed'    — analysis recorded an error for this file.
      'conflict'         — the source changed since the scan's baseline (classify_file: 'stale')
                           AND ACP holds a fix that is unpublished, or was published BEFORE that
                           source change — both sides diverged and neither is simply ahead.
      'acp_newer'        — ACP published a fix and it is newer than the source's current state
                           (this also catches a fix published AFTER a source change that would
                           otherwise look like 'conflict': ACP's copy is the newest word either
                           side has, so it is not a disagreement).
      'publish_pending'  — a fix exists, is unpublished, and the source has not changed (so this
                           is not a 'conflict').
      otherwise, classify_file's own state (stale/unchanged/untracked/unavailable) stands.

    `run_status` is the scan's own scan_runs.status. 'importing' needs it: get_scan's synthetic
    status='discovered' placeholder (no file_records row yet) is otherwise indistinguishable from
    a deliberately-paused ADR 0020 discover-only scan waiting on the user to trigger Assess —
    only 'running' means a file sitting at 'discovered' is actually mid-import right now.

    A file that finishes analysing WHILE OTHERS in the same scan have not yet (a running fan-out
    scan, ADR 0007) is not visible to this function at all — get_scan only returns the
    file_records join once at least one file has one, so a still-importing sibling has no row to
    classify here. That is an existing gap in what get_scan returns mid-scan, not something this
    function can see past; noted, not fixed, here.

    'acp_newer' and the newer-wins carve-out inside 'conflict' both need a live `current` reading
    to compare against, so — like classify_file's own 'stale' — they are only reachable for a
    Drive-tracked file (`source_is_drive`, a drive_file_id and a baseline). A fix that is merely
    unpublished still surfaces as 'publish_pending' for any source, since that needs no comparison
    against the source at all.
    """
    status = (file_row or {}).get("status")
    if status == "discovered" and run_status == "running":
        return {"state": "importing", "baseline": (file_row or {}).get("source_modified"),
                "current": None}
    if status == "error":
        return {"state": "import_failed", "baseline": (file_row or {}).get("source_modified"),
                "current": None}

    base = classify_file(file_row, current, source_is_drive=source_is_drive, fetch_error=fetch_error)

    remediated_at = (file_row or {}).get("remediated_at")
    if not remediated_at:
        return base

    published_at = (file_row or {}).get("published_at")
    pub_dt = parse_rfc3339(published_at) if published_at else None
    cur_dt = parse_rfc3339(current) if current else None
    newer = bool(pub_dt and cur_dt and pub_dt > cur_dt)

    if base["state"] == "stale":
        # Published strictly after the source's current change: ACP's copy is the newest word
        # either side has, so this is 'acp_newer', not a disagreement.
        if newer:
            return {**base, "state": "acp_newer"}
        return {**base, "state": "conflict"}

    if not published_at:
        return {**base, "state": "publish_pending"}

    return {**base, "state": "acp_newer"} if newer else base
