"""The pure staleness classifier — no Drive, no DB. Given a scan-time baseline and the source's
current modifiedTime, decide stale / unchanged / untracked / unavailable."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from source_staleness import (  # noqa: E402
    parse_rfc3339, compare_state, classify_file, classify_sync_state,
)


def test_parse_handles_millis_and_missing_millis_and_junk():
    assert parse_rfc3339("2026-08-01T09:00:00Z") is not None
    assert parse_rfc3339("2026-08-01T09:00:00.123Z") is not None
    assert parse_rfc3339("") is None
    assert parse_rfc3339("not a date") is None
    assert parse_rfc3339(None) is None


def test_compare_state():
    assert compare_state("2026-08-01T09:00:00.000Z", "2026-08-05T14:00:00.000Z") == "stale"
    assert compare_state("2026-08-01T09:00:00.000Z", "2026-08-01T09:00:00.000Z") == "unchanged"
    assert compare_state("2026-08-05T00:00:00.000Z", "2026-08-01T00:00:00.000Z") == "unchanged"  # older
    # A precision difference alone (millis vs none, same instant) is NOT a change.
    assert compare_state("2026-08-01T09:00:00Z", "2026-08-01T09:00:00.000Z") == "unchanged"
    # Unparseable → None (the caller must treat as unknown, never a false 'unchanged').
    assert compare_state("garbage", "2026-08-01T09:00:00Z") is None
    assert compare_state("2026-08-01T09:00:00Z", None) is None


def test_classify_untracked_when_nothing_to_compare():
    tracked = {"source_modified": "2026-08-01T09:00:00.000Z", "drive_file_id": "1a"}
    assert classify_file({"drive_file_id": "1a"}, "x", source_is_drive=True)["state"] == "untracked"          # no baseline
    assert classify_file({"source_modified": "2026-08-01T09:00:00Z"}, "x", source_is_drive=True)["state"] == "untracked"  # no id
    assert classify_file(tracked, "x", source_is_drive=False)["state"] == "untracked"                         # not a Drive scan


def test_classify_stale_and_unchanged():
    row = {"source_modified": "2026-08-01T09:00:00.000Z", "drive_file_id": "1a"}
    assert classify_file(row, "2026-08-05T00:00:00.000Z", source_is_drive=True)["state"] == "stale"
    assert classify_file(row, "2026-08-01T09:00:00.000Z", source_is_drive=True)["state"] == "unchanged"


def test_classify_unavailable_on_fetch_error_or_unparseable():
    row = {"source_modified": "2026-08-01T09:00:00.000Z", "drive_file_id": "1a"}
    r = classify_file(row, None, source_is_drive=True, fetch_error="not_found")
    assert r["state"] == "unavailable" and r["error"] == "not_found"
    r2 = classify_file(row, "garbage", source_is_drive=True)
    assert r2["state"] == "unavailable" and r2["error"] == "unparseable"


# ── classify_sync_state — PRD Phase 3's fuller vocabulary ─────────────────────────────────────

TRACKED = {"source_modified": "2026-08-01T09:00:00.000Z", "drive_file_id": "1a"}


def test_importing_only_while_the_scan_is_actually_running():
    row = {"status": "discovered"}
    assert classify_sync_state(row, None, source_is_drive=True, run_status="running")["state"] == "importing"
    # The SAME 'discovered' placeholder on a scan that is NOT running is an ADR 0020 discover-only
    # scan deliberately waiting on the user to trigger Assess, not an in-progress import.
    r = classify_sync_state(row, None, source_is_drive=True, run_status="completed")
    assert r["state"] != "importing"


def test_import_failed_regardless_of_run_status():
    row = {"status": "error"}
    assert classify_sync_state(row, None, source_is_drive=True, run_status="running")["state"] == "import_failed"
    assert classify_sync_state(row, None, source_is_drive=True, run_status="completed")["state"] == "import_failed"


def test_no_fix_leaves_the_base_classify_file_state_untouched():
    row = {**TRACKED, "status": "PASS"}
    r = classify_sync_state(row, "2026-08-05T00:00:00.000Z", source_is_drive=True)
    assert r["state"] == "stale"       # exactly what classify_file would have said


def test_publish_pending_when_unpublished_and_the_source_has_not_changed():
    for base_current, expect_untouched_error in [
        ("2026-08-01T09:00:00.000Z", None),                 # unchanged
        (None, None),                                       # untracked (no live current at all)
    ]:
        row = {**TRACKED, "status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00"}
        r = classify_sync_state(row, base_current, source_is_drive=True)
        assert r["state"] == "publish_pending"


def test_publish_pending_also_surfaces_when_the_source_is_unavailable():
    # An unpublished fix is worth surfacing even when the source itself can't be confirmed —
    # the two facts are orthogonal.
    row = {**TRACKED, "status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00"}
    r = classify_sync_state(row, None, source_is_drive=True, fetch_error="not_found")
    assert r["state"] == "publish_pending"


def test_conflict_when_the_source_changed_and_the_fix_is_unpublished():
    row = {**TRACKED, "status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00"}
    r = classify_sync_state(row, "2026-08-05T00:00:00.000Z", source_is_drive=True)
    assert r["state"] == "conflict"


def test_conflict_when_the_fix_was_published_before_the_source_changed():
    row = {**TRACKED, "status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00",
           "published_at": "2026-08-03T00:00:00+00:00"}
    r = classify_sync_state(row, "2026-08-05T00:00:00.000Z", source_is_drive=True)   # source changed AFTER the publish
    assert r["state"] == "conflict"


def test_acp_newer_when_the_fix_was_published_after_a_source_change():
    # ACP's own copy is the newest word EITHER side has — not a disagreement.
    row = {**TRACKED, "status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00",
           "published_at": "2026-08-06T00:00:00+00:00"}
    r = classify_sync_state(row, "2026-08-05T00:00:00.000Z", source_is_drive=True)
    assert r["state"] == "acp_newer"


def test_acp_newer_when_the_source_never_changed_at_all():
    row = {**TRACKED, "status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00",
           "published_at": "2026-08-02T12:00:00+00:00"}
    r = classify_sync_state(row, "2026-08-01T09:00:00.000Z", source_is_drive=True)   # source unchanged
    assert r["state"] == "acp_newer"


def test_published_fix_with_no_live_current_to_compare_never_claims_acp_newer():
    # Non-Drive / untracked: there is nothing live to compare the publish against, so this must
    # not assert a claim it cannot back up.
    row = {"status": "PASS", "remediated_at": "2026-08-02T00:00:00+00:00",
           "published_at": "2026-08-03T00:00:00+00:00"}
    r = classify_sync_state(row, None, source_is_drive=False)
    assert r["state"] != "acp_newer"
    assert r["state"] == "untracked"   # classify_file's own base state, since there's no fix claim to add
