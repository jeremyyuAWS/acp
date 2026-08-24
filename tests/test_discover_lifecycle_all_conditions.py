"""Lifecycle rules: all condition types evaluated in a full Discover workflow.

Supplements test_discover_lifecycle_rules.py (which covers modified_at:before, tag rules,
idempotency, delete/archive precedence, Exempted files, and Assess exclusion).

This file covers:
  - age_days vs modified_age_days semantic distinction: "Older than N days" uses created_at;
    "Not modified in last N days" uses source_modified. A file created 10 years ago but
    modified yesterday matches the first rule but NOT the second.
  - modified_age_days:gt (relative days, not absolute date)
  - owner condition
  - source condition
  - doc_class condition
  - size_kb condition
  - multi-condition AND rules with all of the above

Harness mirrors test_discover_lifecycle_rules.py: deferral ON, scanner._list monkeypatched,
core.store → isolated temp Store.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PDF = "application/pdf"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _items():
    """Three files with distinct metadata to exercise all condition types.

    ancient_modified_recently.docx
        created 2000-01-01  (age_days ≈ 9000+)
        modified yesterday  (modified_age_days ≈ 1)
        → matches "older than 3 years" but NOT "not modified in last 30 days"

    old_and_stale.pdf
        created 2015-01-01  (age_days ≈ 4200+)
        modified 2015-06-01 (modified_age_days ≈ 4000+)
        → matches both "older than 3 years" AND "not modified in last 30 days"

    new_small.xlsx
        created 2 days ago, modified 2 days ago
        small (5 KB), owned by jane@x.com, source=sharepoint
        → matches neither age rule; useful for owner/source/size/doc_class conditions
    """
    return [
        {
            "name": "ancient_modified_recently.docx",
            "id": "d-amr", "mime": _DOCX, "source_mime": _DOCX,
            "path": "/Archive/ancient_modified_recently.docx",
            "parent_folder": "/Archive",
            "owner": "cfo@x.com",
            "created_at": "2000-01-01T00:00:00+00:00",
            "source_modified": _days_ago(1),
            "size_kb": 50,
            "checksum": "c-amr",
            "doc_class": "text-document",
            "source": "drive",
        },
        {
            "name": "old_and_stale.pdf",
            "id": "d-oas", "mime": _PDF, "source_mime": _PDF,
            "path": "/Finance/Reports/old_and_stale.pdf",
            "parent_folder": "/Finance/Reports",
            "owner": "cfo@x.com",
            "created_at": "2015-01-01T00:00:00+00:00",
            "source_modified": "2015-06-01T00:00:00+00:00",
            "size_kb": 2500,
            "checksum": "c-oas",
            "doc_class": "pdf-document",
            "source": "drive",
        },
        {
            "name": "new_small.xlsx",
            "id": "d-ns", "mime": _XLSX, "source_mime": _XLSX,
            "path": "/Shared/new_small.xlsx",
            "parent_folder": "/Shared",
            "owner": "jane@x.com",
            "created_at": _days_ago(2),
            "source_modified": _days_ago(2),
            "size_kb": 5,
            "checksum": "c-ns",
            "doc_class": "spreadsheet",
            "source": "sharepoint",
        },
    ]


def _policy(st, name, action, match, *, action_config=None, enabled=True):
    pid = "p-" + name
    st.create_disposition_policy(
        pid, name=name, match=json.dumps(match), action=action,
        action_config=json.dumps(action_config or {}), requires_approval=False, enabled=enabled)
    return pid


def _wire(monkeypatch, st):
    import core
    import scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())


def _discover(scan_id="s1", user="admin@x.com"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": user},
                            {"scan_id": scan_id})


# ── age_days vs modified_age_days: the critical semantic distinction ──────────────

def test_age_days_uses_created_at_not_source_modified(isolated_store, monkeypatch):
    """'Older than N days' (age_days) is based on created_at, not last-modified.

    ancient_modified_recently.docx was created in 2000 (age_days ≈ 9000) but modified
    yesterday (modified_age_days ≈ 1). An "older than 3 years" archive rule should flag it
    even though it was recently touched.
    """
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive",
            [{"field": "age_days", "op": "gt", "value": 1095}])  # 3 years
    _discover()

    # ancient_modified_recently.docx: created 2000 → age_days ≈ 9000 → MATCH
    got = st.get_lifecycle_status("s1", "ancient_modified_recently.docx")
    assert got["lifecycle_status"] == "Archive Candidate", \
        "file created in 2000 must match age_days>1095 despite recent modification"

    # new_small.xlsx: created 2 days ago → age_days = 2 → NO MATCH
    got2 = st.get_lifecycle_status("s1", "new_small.xlsx")
    assert got2["lifecycle_status"] == "Active"


def test_modified_age_days_uses_source_modified_not_created_at(isolated_store, monkeypatch):
    """'Not modified in last N days' (modified_age_days) is based on source_modified.

    ancient_modified_recently.docx was modified yesterday so modified_age_days ≈ 1.
    A "not modified in last 30 days" rule must NOT flag it, even though it was created in 2000.
    old_and_stale.pdf was modified in 2015, so modified_age_days ≈ 4000+ → MATCH.
    """
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_age_days", "op": "gt", "value": 30}])
    _discover()

    # ancient_modified_recently.docx: modified yesterday → modified_age_days ≈ 1 → NO MATCH
    got = st.get_lifecycle_status("s1", "ancient_modified_recently.docx")
    assert got["lifecycle_status"] == "Active", \
        "file modified yesterday must NOT match modified_age_days>30 despite 2000 creation"

    # old_and_stale.pdf: modified 2015 → modified_age_days ≈ 4000 → MATCH
    got2 = st.get_lifecycle_status("s1", "old_and_stale.pdf")
    assert got2["lifecycle_status"] == "Archive Candidate"


def test_age_days_and_modified_age_days_both_required_catches_only_truly_old_and_stale(
        isolated_store, monkeypatch):
    """Combining both conditions catches files that are old AND stale, not recently-touched old ones."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old-and-stale", "archive", [
        {"field": "age_days", "op": "gt", "value": 1095},        # created 3+ years ago
        {"field": "modified_age_days", "op": "gt", "value": 365},  # not modified in 1+ year
    ])
    _discover()

    # ancient_modified_recently.docx: old creation (✓) but modified yesterday (✗) → Active
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Active"

    # old_and_stale.pdf: old creation (✓) AND stale modification (✓) → Archive Candidate
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")[
        "lifecycle_status"] == "Archive Candidate"

    # new_small.xlsx: recent creation (✗) → Active
    assert st.get_lifecycle_status("s1", "new_small.xlsx")["lifecycle_status"] == "Active"


# ── owner condition ───────────────────────────────────────────────────────────────

def test_owner_condition_matches_exact(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-jane", "archive",
            [{"field": "owner", "op": "eq", "value": "jane@x.com"}])
    _discover()

    # new_small.xlsx is owned by jane@x.com → Archive Candidate
    assert st.get_lifecycle_status("s1", "new_small.xlsx")[
        "lifecycle_status"] == "Archive Candidate"

    # cfo-owned files → Active
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")["lifecycle_status"] == "Active"
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Active"


def test_owner_ne_excludes_specific_owner(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    # Archive everything NOT owned by jane — i.e., cfo-owned files
    _policy(st, "archive-not-jane", "archive",
            [{"field": "owner", "op": "ne", "value": "jane@x.com"}])
    _discover()

    assert st.get_lifecycle_status("s1", "new_small.xlsx")["lifecycle_status"] == "Active"
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")[
        "lifecycle_status"] == "Archive Candidate"
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Archive Candidate"


# ── source condition ──────────────────────────────────────────────────────────────

def test_source_condition_matches_by_scan_source(isolated_store, monkeypatch):
    """The 'source' lifecycle condition matches the scan's source (drive/sharepoint/local),
    not a per-file field. All files from a scan share the same source."""
    import core
    import scanner
    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())

    # Archive rule targeting only SharePoint scans.
    _policy(st, "archive-sp", "archive",
            [{"field": "source", "op": "eq", "value": "sharepoint"}])

    # Scan with source=sharepoint → all three files match
    import handlers
    handlers._scan_discover({"scan_id": "sp1", "source": "sharepoint", "user": "admin@x.com"},
                            {"scan_id": "sp1"})

    assert st.get_lifecycle_status("sp1", "new_small.xlsx")["lifecycle_status"] == "Archive Candidate"
    assert st.get_lifecycle_status("sp1", "old_and_stale.pdf")["lifecycle_status"] == "Archive Candidate"
    assert st.get_lifecycle_status("sp1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Archive Candidate"

    # Scan with source=local → rule does not match — files stay Active
    handlers._scan_discover({"scan_id": "lo1", "source": "local", "user": "admin@x.com"},
                            {"scan_id": "lo1"})

    assert st.get_lifecycle_status("lo1", "new_small.xlsx")["lifecycle_status"] == "Active"


# ── doc_class condition ───────────────────────────────────────────────────────────

def test_doc_class_condition_matches_pdf(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-pdfs", "archive",
            [{"field": "doc_class", "op": "eq", "value": "pdf-document"}])
    _discover()

    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")[
        "lifecycle_status"] == "Archive Candidate"
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Active"
    assert st.get_lifecycle_status("s1", "new_small.xlsx")["lifecycle_status"] == "Active"


def test_doc_class_condition_matches_spreadsheet(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-sheets", "archive",
            [{"field": "doc_class", "op": "eq", "value": "spreadsheet"}])
    _discover()

    assert st.get_lifecycle_status("s1", "new_small.xlsx")[
        "lifecycle_status"] == "Archive Candidate"
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")["lifecycle_status"] == "Active"


# ── size_kb condition ─────────────────────────────────────────────────────────────

def test_size_kb_condition_archives_large_files(isolated_store, monkeypatch):
    """'Larger than N KB' targets old large files for storage cleanup."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-large", "archive",
            [{"field": "size_kb", "op": "gt", "value": 1000}])
    _discover()

    # old_and_stale.pdf is 2500 KB → Archive Candidate
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")[
        "lifecycle_status"] == "Archive Candidate"
    # new_small.xlsx is 5 KB → Active
    assert st.get_lifecycle_status("s1", "new_small.xlsx")["lifecycle_status"] == "Active"
    # ancient_modified_recently.docx is 50 KB → Active
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Active"


def test_size_kb_none_does_not_match(isolated_store, monkeypatch):
    """Files with no size metadata must not be flagged by size_kb rules."""
    import scanner

    def _sizeless_items():
        return [{"name": "nosizeinfo.docx", "id": "d-ns2", "mime": _DOCX, "source_mime": _DOCX,
                 "path": "/X/nosizeinfo.docx", "parent_folder": "/X", "owner": "a@x.com",
                 "created_at": "2020-01-01T00:00:00+00:00", "source_modified": "2020-01-01T00:00:00+00:00",
                 "size_kb": None, "checksum": "c-x", "doc_class": "text-document", "source": "drive"}]

    st = isolated_store
    import core
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _sizeless_items())

    _policy(st, "archive-large", "archive",
            [{"field": "size_kb", "op": "gt", "value": 0}])
    _discover()

    assert st.get_lifecycle_status("s1", "nosizeinfo.docx")["lifecycle_status"] == "Active"


# ── multi-condition AND: realistic combined policy ────────────────────────────────

def test_combined_condition_large_old_pdf(isolated_store, monkeypatch):
    """Realistic 'archive large old PDFs' rule: doc_class + size_kb + age_days."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-large-old-pdf", "archive", [
        {"field": "doc_class", "op": "eq", "value": "pdf-document"},
        {"field": "size_kb", "op": "gt", "value": 1000},
        {"field": "age_days", "op": "gt", "value": 1095},
    ])
    _discover()

    # old_and_stale.pdf: pdf ✓, 2500 KB ✓, created 2015 ✓ → Archive Candidate
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")[
        "lifecycle_status"] == "Archive Candidate"

    # ancient_modified_recently.docx: NOT pdf → Active
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Active"

    # new_small.xlsx: NOT pdf, NOT large, NOT old → Active
    assert st.get_lifecycle_status("s1", "new_small.xlsx")["lifecycle_status"] == "Active"


def test_combined_condition_stale_files_from_specific_owner(isolated_store, monkeypatch):
    """'Archive cfo-owned files not modified in 2+ years': owner + modified_age_days."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-cfo-stale", "archive", [
        {"field": "owner", "op": "eq", "value": "cfo@x.com"},
        {"field": "modified_age_days", "op": "gt", "value": 730},
    ])
    _discover()

    # old_and_stale.pdf: cfo ✓, modified 2015 ✓ → Archive Candidate
    assert st.get_lifecycle_status("s1", "old_and_stale.pdf")[
        "lifecycle_status"] == "Archive Candidate"

    # ancient_modified_recently.docx: cfo ✓, but modified yesterday ✗ → Active
    assert st.get_lifecycle_status("s1", "ancient_modified_recently.docx")[
        "lifecycle_status"] == "Active"

    # new_small.xlsx: NOT cfo ✗ → Active
    assert st.get_lifecycle_status("s1", "new_small.xlsx")["lifecycle_status"] == "Active"
