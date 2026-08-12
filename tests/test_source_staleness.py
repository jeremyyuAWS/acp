"""The pure staleness classifier — no Drive, no DB. Given a scan-time baseline and the source's
current modifiedTime, decide stale / unchanged / untracked / unavailable."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from source_staleness import parse_rfc3339, compare_state, classify_file  # noqa: E402


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
