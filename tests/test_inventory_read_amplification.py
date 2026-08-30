"""Authorising an inventory page must not read the whole inventory (PRD H-09).

`GET /scans/{sid}/inventory` used get_scan() purely as an ownership gate — the result is
compared to None and otherwise discarded. But get_scan() assembles the entire scan aggregate to
produce it, and on a DISCOVER-ONLY run (ADR 0020: inventory listed, analysis deferred, so no
file_records exist yet) it takes the `if not files:` fallback and reads the whole scan_inventory
table ordered by file. That is the exact state this endpoint exists to serve, so the pathological
case was the normal case.

Measured on the 2026-08-30 incident's own 6,916-row inventory before the fix: a full seven-page
load read 55,328 rows from the database to return 6,916 — 8.0x amplification, every bit of it in
a gate that needs one row. This endpoint is one of the routes that 500'd during that incident, at
offset=5000, while the API replica's connection pool was exhausted.

get_scan_head() is the narrow lookup that already existed for /workspace/bootstrap: one indexed
SELECT on scan_runs, identical owner semantics (None for a missing OR a foreign scan).
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"
_NOW = datetime.now(timezone.utc).isoformat()
INVENTORY_ROWS = 400          # enough to make amplification unmistakable, small enough to be fast
PAGE = 100
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.fixture()
def discovered_scan(gated_client, isolated_store):
    """A discover-only scan with an inventory and no file_records — the ADR 0020 shape."""
    r = gated_client(OWNER).post("/scans?source=local&queue=true&fanout=true")
    assert r.status_code == 200, r.text
    sid = r.json()["scan_id"]
    isolated_store.init_scan_run(sid, "local", total=INVENTORY_ROWS, started_at=_NOW,
                                 rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                                 owner=OWNER, status="discovered")
    isolated_store.add_inventory(sid, [
        {"drive_file_id": f"f{i}", "file": f"doc{i:04d}.docx", "mime": _DOCX,
         "size": 1000 + i, "path": f"/estate/doc{i:04d}.docx"}
        for i in range(INVENTORY_ROWS)])
    return sid


def _rows_read(store, fn):
    """Count rows the adapter hands back for one call — the DB work, not the response size."""
    adapter = store._db
    original = adapter.fetchall
    seen = {"n": 0}

    def counting(cur):
        out = original(cur)
        seen["n"] += len(out or [])
        return out

    adapter.fetchall = counting
    try:
        result = fn()
    finally:
        adapter.fetchall = original
    return seen["n"], result


def test_a_page_does_not_read_the_whole_inventory_to_authorise_itself(
        gated_client, isolated_store, discovered_scan):
    """THE regression. Reading one page must cost about one page, not the whole estate."""
    sid = discovered_scan
    read, r = _rows_read(isolated_store,
                         lambda: gated_client(OWNER).get(
                             f"/scans/{sid}/inventory?offset=0&limit={PAGE}"))
    assert r.status_code == 200, r.text
    returned = len(r.json()["rows"])
    assert returned == PAGE

    # Generous ceiling: the page itself plus a small constant for count/lookup rows. The old
    # gate read every one of the INVENTORY_ROWS on top of the page, so it lands far above this.
    assert read <= PAGE + 20, (
        f"authorising one {PAGE}-row page read {read} rows from the database — the ownership "
        f"gate is assembling the whole scan aggregate again (H-09)")


def test_a_full_paginated_load_stays_proportional(gated_client, isolated_store, discovered_scan):
    """The per-page waste is what compounds: seven pages meant seven whole-inventory reads."""
    sid = discovered_scan
    total_read = 0
    total_returned = 0
    for offset in range(0, INVENTORY_ROWS, PAGE):
        read, r = _rows_read(isolated_store,
                             lambda o=offset: gated_client(OWNER).get(
                                 f"/scans/{sid}/inventory?offset={o}&limit={PAGE}"))
        assert r.status_code == 200, r.text
        total_read += read
        total_returned += len(r.json()["rows"])

    assert total_returned == INVENTORY_ROWS
    amplification = total_read / total_returned
    assert amplification < 1.5, (
        f"a full inventory load read {total_read} rows to return {total_returned} "
        f"({amplification:.1f}x amplification) — H-09")


def test_the_gate_still_refuses_another_owners_scan(gated_client, discovered_scan):
    """The cheap lookup must not become a cheap way past owner isolation. get_scan_head applies
    the same check get_scan did; this pins that swapping them did not widen access."""
    sid = discovered_scan
    r = gated_client(OTHER).get(f"/scans/{sid}/inventory?offset=0&limit={PAGE}")
    assert r.status_code == 404, f"another owner reached the inventory: {r.status_code}"
    assert gated_client(OTHER).get(f"/scans/{sid}/inventory.csv").status_code == 404


def test_a_missing_scan_is_still_404(gated_client):
    assert gated_client(OWNER).get("/scans/does-not-exist/inventory").status_code == 404
    assert gated_client(OWNER).get("/scans/does-not-exist/inventory.csv").status_code == 404


def test_the_page_contents_are_unchanged(gated_client, isolated_store, discovered_scan):
    """A cheaper gate must return exactly the same rows — same order, same capability fields."""
    sid = discovered_scan
    r = gated_client(OWNER).get(f"/scans/{sid}/inventory?offset=0&limit={PAGE}")
    body = r.json()
    assert body["total"] == INVENTORY_ROWS
    assert body["offset"] == 0 and body["limit"] == PAGE
    assert [row["file"] for row in body["rows"]] == [f"doc{i:04d}.docx" for i in range(PAGE)]
    # _inv_capability still decorates each row.
    assert all(row.get("format") and row.get("status") for row in body["rows"])
