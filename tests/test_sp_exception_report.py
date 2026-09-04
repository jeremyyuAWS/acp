"""The exportable exception report — everything a scan could NOT read.

An estate report says what was found. This says what was MISSED, which is the half an auditor and
an IT admin act on: a site whose consent lapsed, a library that throttled out, a selection the
site cap refused. Those facts have been on the scan's scope since Phase 1 and have only ever been
visible inside the app, one run at a time — a customer chasing thirty consents needs a list they
can send to somebody.

The judgement that shapes the file: a site that COMPLETED is not an exception, however little it
held. An empty library is an answer about the tenant, and listing it here would bury the sites
that actually failed under the ones that are simply small.
"""
from __future__ import annotations

import csv
import io as _io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


def _rows(scope):
    """Drive the endpoint's body over a scope, without the app or a database."""
    import core
    from routes import scans as _scans

    class _Req:
        headers = {}
        state = type("S", (), {"user_email": "o@example.com"})()

    class _Store:
        def get_scan_head(self, sid, owner=None):
            return {"id": sid}

        def get_scan(self, sid, owner=None):
            return {"run": {"source": "sharepoint", "scope": scope}}

    old = core.store
    core.store = _Store()
    try:
        resp = _scans.scan_exceptions_csv("s1", _Req())
    finally:
        core.store = old
    body = resp.body.decode() if isinstance(resp.body, bytes) else resp.body
    return list(csv.DictReader(_io.StringIO(body)))


SITES = [
    {"id": "S1", "name": "Finance", "status": "complete", "listed": 412,
     "libraries": [{"id": "d1", "name": "Documents", "mode": "delta"}]},
    {"id": "S2", "name": "HR", "status": "blocked", "listed": 0, "libraries": [],
     "error": "Sites.Read.All not granted — needs admin consent"},
    {"id": "S3", "name": "Legal", "status": "skipped", "listed": 0, "libraries": [],
     "error": "over the 30-site limit for one scan"},
    {"id": "S4", "name": "Ops", "status": "partial", "listed": 12,
     "libraries": [{"id": "d4", "name": "Archive", "mode": "full",
                    "full_reason": "the delta cursor is 9 days old"}],
     "error": "library Broken: throttled"},
]


def test_it_lists_only_what_actually_failed():
    """A site that completed is not an exception. Listing every site would bury the four that
    need action under the twenty-six that do not."""
    ids = {r["site_id"] for r in _rows({"sites": SITES})}
    assert ids == {"S2", "S3", "S4"}
    assert "S1" not in ids


def test_each_row_names_the_site_the_status_and_the_reason():
    """"Something failed" is not actionable. Which site, in what way, and why — those three are
    what turn the report into a task list."""
    row = next(r for r in _rows({"sites": SITES}) if r["site_id"] == "S2")
    assert row["level"] == "site"
    assert row["site_name"] == "HR" and row["status"] == "blocked"
    assert "admin consent" in row["reason"]


def test_a_blocked_site_and_a_capped_one_are_distinguishable():
    """Different problems with different fixes — a permission versus a second scan or a higher
    limit — and an operator triages by exactly that difference."""
    got = {r["site_id"]: (r["status"], r["reason"]) for r in _rows({"sites": SITES})}
    assert got["S2"][0] == "blocked" and "consent" in got["S2"][1]
    assert got["S3"][0] == "skipped" and "site limit" in got["S3"][1]


def test_a_library_that_had_to_be_re_walked_is_reported_at_LIBRARY_level():
    """Sites and libraries fail independently: a site can be readable while one of its libraries
    throttles out, and merging them would hide the working nine tenths behind the broken tenth."""
    lib = next(r for r in _rows({"sites": SITES}) if r["level"] == "library")
    assert lib["site_id"] == "S4" and lib["library_name"] == "Archive"
    assert "cursor is 9 days old" in lib["reason"]


def test_a_library_that_synced_normally_is_not_an_exception():
    """S1's library ran on its delta cursor, which is the feature working."""
    assert all(r["library_id"] != "d1" for r in _rows({"sites": SITES}))


def test_an_all_clear_scan_returns_a_HEADER_and_no_rows():
    """EMPTY IS A REAL ANSWER. A report that 404s when nothing failed is indistinguishable from
    one that could not be produced — and the difference is exactly what the reader is asking."""
    rows = _rows({"sites": [SITES[0]]})
    assert rows == []


def test_a_scan_with_no_sites_at_all_still_answers():
    """A Drive scan, a local corpus, a OneDrive run. Nothing to report is not an error."""
    assert _rows({"kind": "drive"}) == []
    assert _rows(None) == []


def test_a_scope_stored_as_json_text_is_read():
    """scan_runs.scope comes back as a string on some paths and a dict on others. A reader that
    handled one would produce an empty exception report on the other — an all-clear that is
    really a parse failure, which is the worst possible thing for this particular file to say."""
    assert {r["site_id"] for r in _rows(json.dumps({"sites": SITES}))} == {"S2", "S3", "S4"}


def test_a_malformed_scope_does_not_500_the_export():
    assert _rows("not json at all") == []
    assert _rows({"sites": ["nonsense", None]}) == []


def test_the_route_is_registered_for_the_same_capability_as_the_estate_export():
    """An export nobody is authorised to call is an export that does not exist. Registered
    alongside inventory.csv because it answers the other half of the same question."""
    import workspace_capability_map as m
    src = Path(ROOT / "api" / "workspace_capability_map.py").read_text()
    assert '"/scans/{sid}/exceptions.csv"' in src
    assert m is not None
