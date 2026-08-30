"""Per-file estate inventory: paginated list + CSV export (Discovery gap G2).

The estate is persisted per file in scan_inventory, but no client could LIST or EXPORT it — the
dashboard only ever saw a capped 200/status sample. These pin the two endpoints that expose the
durable rows: owner-scoped, DB-paginated, capability-enriched, and a full CSV export.
"""
import csv
import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

ROOT = Path(__file__).resolve().parent.parent
DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OWNER = "jeremyyu.movate@gmail.com"
OTHER_OWNER = "someone.else@example.com"


# ── store: DB-level pagination ────────────────────────────────────────────────────────────────
def test_list_inventory_page_pages_from_the_db_by_file(isolated_store):
    s = isolated_store
    s.add_inventory("scan1", [{"file": f"f{i:03d}.docx", "mime": DOC, "owner": "a@b.c", "size_kb": i}
                              for i in range(10)])
    assert s.count_inventory("scan1") == 10
    first = s.list_inventory_page("scan1", limit=4, offset=0)
    assert [r["file"] for r in first] == ["f000.docx", "f001.docx", "f002.docx", "f003.docx"]  # ORDER BY file
    last = s.list_inventory_page("scan1", limit=4, offset=8)
    assert [r["file"] for r in last] == ["f008.docx", "f009.docx"]     # partial final page, no error
    assert first[0]["owner"] == "a@b.c" and first[0]["size_kb"] == 0    # source metadata round-trips


# ── store: the narrow per-page ownership check (H-09) ──────────────────────────────────────────
# scan_owned_by is what the route now calls on every page instead of the full get_scan aggregate.
# It must enforce the exact same isolation get_scan does — a positive case, a negative case, and
# the two ways "no" can happen (wrong owner vs. no such scan at all) collapsing to the same
# answer so a guessed scan_id cannot be used to learn whether it exists.
def test_scan_owned_by_accepts_the_true_owner(isolated_store):
    s = isolated_store
    s.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                "files": []})
    assert s.scan_owned_by("s1", owner=OWNER) is True


def test_scan_owned_by_rejects_a_different_owner(isolated_store):
    s = isolated_store
    s.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                "files": []})
    # Guessing a real scan_id that belongs to someone else must read exactly like a scan_id
    # that does not exist at all — never distinguishable from the caller's side.
    assert s.scan_owned_by("s1", owner=OTHER_OWNER) is False
    assert s.scan_owned_by("no-such-scan", owner=OTHER_OWNER) is False


def test_scan_owned_by_skips_the_check_when_owner_is_none(isolated_store):
    # owner=None is the same "isolation off" escape hatch get_scan(sid, owner=None) has —
    # existence alone is enough.
    s = isolated_store
    s.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                "files": []})
    assert s.scan_owned_by("s1", owner=None) is True


# ── endpoint wiring (source-level, matching the repo's route-test style) ───────────────────────
def test_inventory_endpoints_owner_scoped_paginated_and_capability_enriched():
    src = (ROOT / "api" / "routes" / "scans.py").read_text()
    assert '@router.get("/scans/{sid}/inventory")' in src
    assert '@router.get("/scans/{sid}/inventory.csv")' in src

    listbody = re.search(r"def scan_inventory_list\(.*?(?=\n@router)", src, re.S).group(0)
    # H-09: the per-page ownership check is a narrow scan_owned_by lookup, not the full get_scan
    # aggregate — get_scan is what the CSV export (whole-estate, one call) can afford; this route
    # pays its authorization cost on every one of up to 30 pages for a 30k-file estate.
    assert "scan_owned_by(sid, owner=_owner(request))" in listbody and "404" in listbody
    assert "get_scan(" not in listbody                                                # not the full aggregate
    assert "limit: int = Query(200, ge=1, le=1000)" in listbody                       # paginated, bounded
    assert "list_inventory_page(sid, limit=limit, offset=offset)" in listbody         # DB paging, not fetch-all
    assert '"total": core.store.count_inventory(sid)' in listbody                     # real total, own lean query
    assert "_inv_capability(r)" in listbody                                           # capability-enriched

    csvbody = re.search(r"def scan_inventory_csv\(.*?(?=\n@router)", src, re.S).group(0)
    assert 'media_type="text/csv"' in csvbody and "attachment; filename=" in csvbody  # a download
    assert "list_inventory(sid)" in csvbody                                           # ALL rows, not a page
    assert '"format", "status"' in csvbody                                            # capability columns exported


def test_inv_capability_derives_format_status_from_the_stored_mime():
    body = re.search(r"def _inv_capability\(.*?(?=\ndef |\n@router)",
                     (ROOT / "api" / "routes" / "scans.py").read_text(), re.S).group(0)
    assert "estate_inventory" in body and "classify" in body
    assert 'row.get("mime")' in body   # classification comes from the persisted mime, same as the estate summary


# ── the CSV export actually carries the rule and the override, not just lifecycle_status ───────
# store.list_inventory (_INV_COLS) already selected lifecycle_rule_id/lifecycle_reason/the three
# override columns — the CSV route just never put them in its own `cols` list, so an auditor
# exporting the estate saw THAT a file was tagged but not WHICH rule, WHY, or whether a human had
# overridden the recommendation (lifecycle rules #8). A real request/response round trip, not a
# source grep: the source-grep test above only pins that SOME capability columns are in the list.
@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    # Both OWNER and OTHER_OWNER are valid signed-in accounts — the isolation test below needs a
    # SECOND real, authenticated owner, not an unauthenticated request, to prove the 404 comes
    # from ownership and not from failing auth first.
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, OTHER_OWNER))
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {OWNER}"})
    return client, isolated_store


def test_csv_export_carries_the_rule_reason_and_any_override(client):
    c, st = client
    st.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                 "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                 "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                 "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                 "files": []})
    st.add_inventory("s1", [{"file": "Finance/old.pdf", "doc_class": "pdf"}])
    st.set_lifecycle_status("s1", "Finance/old.pdf", "Archive Candidate",
                            rule_id="r-42", reason="matched archive rule 'stale finance'")
    st.override_lifecycle("s1", "Finance/old.pdf", reason="under active legal hold", actor=OWNER)

    r = c.get("/scans/s1/inventory.csv")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1
    row = rows[0]
    assert row["lifecycle_status"] == "Archive Candidate"
    assert row["lifecycle_rule_id"] == "r-42"
    assert row["lifecycle_reason"] == "matched archive rule 'stale finance'"
    assert row["lifecycle_override_reason"] == "under active legal hold"
    assert row["lifecycle_overridden_by"] == OWNER
    assert row["lifecycle_overridden_at"]   # stamped, exact value not asserted


# ── GET /scans/{sid}/inventory round trip against the narrowed check (H-09) ────────────────────
def test_owner_pages_through_their_own_inventory(client):
    """Positive case: the narrow scan_owned_by check must not have broken the owner's own read —
    each page of a real multi-page inventory still comes back with the right rows and the same
    real total on every page."""
    c, st = client
    st.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                 "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                 "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                 "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                 "files": []})
    st.add_inventory("s1", [{"file": f"f{i:03d}.docx", "doc_class": "docx"} for i in range(5)])

    r1 = c.get("/scans/s1/inventory", params={"offset": 0, "limit": 2})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["total"] == 5
    assert [row["file"] for row in b1["rows"]] == ["f000.docx", "f001.docx"]

    r2 = c.get("/scans/s1/inventory", params={"offset": 2, "limit": 2})
    b2 = r2.json()
    assert b2["total"] == 5   # same real total on the second page, not a page-scoped count
    assert [row["file"] for row in b2["rows"]] == ["f002.docx", "f003.docx"]


def test_a_different_owner_cannot_page_through_this_scan_by_guessing_its_id(client):
    """Negative case: the whole point of H-09 is that the FASTER check must still be a REAL check.
    An owner who is genuinely signed in, just not the owner of this scan_id, gets exactly the
    same 404 an unauthenticated or made-up scan_id would — never the data, never a distinguishing
    error that would let them learn the scan_id is real."""
    c, st = client
    st.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                 "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                 "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                 "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                 "files": []})
    st.add_inventory("s1", [{"file": "Finance/old.pdf", "doc_class": "pdf"}])

    r_wrong_owner = c.get("/scans/s1/inventory", headers={"Authorization": f"Bearer {OTHER_OWNER}"})
    assert r_wrong_owner.status_code == 404
    assert "old.pdf" not in r_wrong_owner.text   # no row data leaked into the error body either

    # Same 404, same body shape, as a scan_id that plain does not exist — not distinguishable.
    r_missing = c.get("/scans/no-such-scan/inventory", headers={"Authorization": f"Bearer {OTHER_OWNER}"})
    assert r_missing.status_code == 404
    assert r_missing.json() == r_wrong_owner.json()


def test_a_small_page_request_reports_the_full_total_not_a_page_scoped_count(client):
    """count-only guardrail: a caller asking for a small page must still see the REAL population
    size in `total` (count_inventory is its own lean COUNT(*), not derived from len(rows)) — and
    must never get MORE rows back than it asked for, i.e. a 'just tell me the count' shaped
    request is never silently upgraded into a full-estate row dump."""
    c, st = client
    st.save_scan({"_scan_id": "s1", "started_at": "2026-08-18T10:00:00+00:00",
                 "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": OWNER,
                 "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                 "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                 "files": []})
    st.add_inventory("s1", [{"file": f"f{i:03d}.docx", "doc_class": "docx"} for i in range(50)])

    r = c.get("/scans/s1/inventory", params={"offset": 0, "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 50        # the real population, not "1" and not len(rows)
    assert len(body["rows"]) == 1      # never more than the caller asked for
