"""Source-staleness baseline: the source file's modifiedTime at scan time must round-trip through
BOTH file_records write paths — save_scan (in-process/local) and save_file_result (fan-out, the
production path) — so the Release Center can later compare it to the source's CURRENT modifiedTime.

NULL when absent (pre-migration scans, non-Drive / SharePoint / upload files): those are 'untracked'
downstream, never falsely reported 'unchanged'.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _by_file(scan):
    return {f["file"]: f for f in scan["files"]}


def test_save_scan_roundtrips_source_modified(isolated_store):
    # INSERT site 1 — save_scan (the in-process/local scan path).
    s = isolated_store
    report = {"started_at": "2026-08-01T10:00:00+00:00",
              "completed_at": "2026-08-01T10:01:00+00:00",
              "source": "drive",
              "rubric": {"name": "WCAG 2.1 AA", "hash": "abc123"},
              "summary": {"files": 2, "certifiable": 2, "uncertain": 0, "error": 0, "avg_score": 95},
              "files": [
                  {"file": "policy.docx", "engine": "office", "status": "PASS", "score": 95,
                   "compliant": 1, "skipped_rules": 0, "issues": [],
                   "drive_file_id": "1ab", "source_modified": "2026-08-01T09:00:00.000Z"},
                  # No source_modified key at all — a non-Drive file, or one scanned before this shipped.
                  {"file": "legacy.docx", "engine": "office", "status": "PASS", "score": 95,
                   "compliant": 1, "skipped_rules": 0, "issues": []},
              ]}
    sid = s.save_scan(report)
    files = _by_file(s.get_scan(sid))
    assert files["policy.docx"]["source_modified"] == "2026-08-01T09:00:00.000Z"
    assert files["legacy.docx"]["source_modified"] is None


def test_save_file_result_roundtrips_and_upserts_source_modified(isolated_store):
    # INSERT site 2 — save_file_result (the fan-out production path), including the UPSERT branch.
    s = isolated_store
    s.init_scan_run("s1", "drive", total=2, started_at="t0", rubric_name="r", rubric_hash="h")
    s.save_file_result("s1", {"file": "a.docx", "engine": "office", "status": "analysed",
                              "score": 90, "compliant": 1, "skipped_rules": 0, "issues": [],
                              "drive_file_id": "1a", "source_modified": "2026-08-01T09:00:00.000Z"}, "t1")
    s.save_file_result("s1", {"file": "b.docx", "engine": "office", "status": "analysed",
                              "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}, "t1")
    files = _by_file(s.get_scan("s1"))
    assert files["a.docx"]["source_modified"] == "2026-08-01T09:00:00.000Z"
    assert files["b.docx"]["source_modified"] is None

    # A re-scan of the same file writes a newer mtime — the UPSERT's DO UPDATE SET must refresh the
    # baseline (EXCLUDED.source_modified), which is what clears a "stale" badge after a re-scan.
    s.save_file_result("s1", {"file": "a.docx", "engine": "office", "status": "analysed",
                              "score": 90, "compliant": 1, "skipped_rules": 0, "issues": [],
                              "drive_file_id": "1a", "source_modified": "2026-08-05T14:00:00.000Z"}, "t2")
    files = _by_file(s.get_scan("s1"))
    assert files["a.docx"]["source_modified"] == "2026-08-05T14:00:00.000Z"


def test_drive_fields_mask_requests_modified_time():
    # The baseline is only ever captured if the Drive listing asks for modifiedTime — guard the mask
    # against an accidental removal (it would silently make every file 'untracked').
    import provenance
    assert "modifiedTime" in provenance.DRIVE_FIELDS
