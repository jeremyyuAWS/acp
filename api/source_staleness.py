"""Pure source-staleness classification for the Release Center's /source-status endpoint.

Kept free of Drive and the DB so the decision logic is unit-testable: given the source's
modifiedTime captured at scan time (the baseline) and its CURRENT modifiedTime, is the source
newer than the scan? Everything that isn't a timestamp comparison — no baseline, no Drive id, a
scan whose source isn't Drive, a Drive fetch that failed — is classified here too, from inputs
the endpoint passes in, so the endpoint stays a thin adapter.

States: 'stale' (source changed since the scan), 'unchanged', 'untracked' (nothing to compare —
never a false 'unchanged'), 'unavailable' (the source couldn't be read, or a timestamp wouldn't
parse).
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
