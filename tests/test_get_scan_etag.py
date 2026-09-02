"""GET /scans/{sid} — ETag / If-None-Match conditional fetch.

get_scan() is the one genuinely heavy read in the app (file_records + issue_records joins).
scan_runs.revision is bumped on every write that would change this response (Discover, Assess,
Remediate, Publish all route through _bump_scan_revision — see api/store.py), so it is the exact
freshness key an ETag needs: a caller holding a scan at revision N can send
`If-None-Match: W/"N"` and skip paying for a response that would be identical.

What this pins:
  * a fresh fetch returns 200 with an ETag header
  * a matching If-None-Match returns 304 with no body
  * a stale If-None-Match (old revision) returns the full 200 payload with a NEW ETag
  * a revision bump invalidates a previously-valid ETag
  * a nonexistent scan 404s regardless of If-None-Match
  * owner scoping still applies under conditional fetch — a foreign owner's request 404s
    rather than leaking a 304 that would confirm the scan exists
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _seed(st, sid: str, owner: str = "demo"):
    """A scan owned by `owner` — "demo" is _owner()'s unauthenticated default, so the route
    resolves it without an auth header."""
    st.init_scan_run(sid, "drive", 1, "2026-08-29T00:00:00Z", "default", "rh",
                     owner=owner, status="discovered")


# ── the happy path ────────────────────────────────────────────────────────────

def test_first_fetch_returns_200_with_an_etag(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1")
    assert r.status_code == 200
    assert r.json()["run"]["id"] == "s1"
    assert r.headers["etag"] == 'W/"0"', "a freshly-created scan has never had its revision bumped"
    assert r.headers["cache-control"] == "private, no-cache"


def test_each_assessed_file_invalidates_the_discovery_payload(client, isolated_store):
    _seed(isolated_store, "s1")
    old_etag = client.get("/scans/s1").headers["etag"]

    isolated_store.save_file_result("s1", {
        "file": "policy.docx", "engine": "office", "status": "assessed", "score": 82,
        "compliant": 1, "skipped_rules": 0, "issues": [],
    }, "2026-08-30T00:00:00Z")

    fresh = client.get("/scans/s1", headers={"If-None-Match": old_etag})
    assert fresh.status_code == 200
    assert fresh.headers["etag"] == 'W/"1"'
    assert [f["file"] for f in fresh.json()["files"]] == ["policy.docx"]


def test_remediation_progress_is_never_cacheable(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1/remediation-status")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_remediation_progress_stream_is_sse_and_finishes_when_queue_is_empty(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1/remediation/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert '"in_flight": 0' in r.text
    assert "event: done" in r.text


def test_matching_if_none_match_returns_304_with_no_body(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1", headers={"If-None-Match": 'W/"0"'})
    assert r.status_code == 304
    assert r.content == b""


def test_stale_if_none_match_returns_the_full_payload(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1", headers={"If-None-Match": 'W/"99"'})
    assert r.status_code == 200
    assert r.json()["run"]["id"] == "s1"
    assert r.headers["etag"] == 'W/"0"'


# ── a revision bump invalidates a previously-valid ETag ───────────────────────

def test_revision_bump_invalidates_a_previously_valid_etag(client, isolated_store):
    _seed(isolated_store, "s1")
    first = client.get("/scans/s1")
    old_etag = first.headers["etag"]
    assert old_etag == 'W/"0"'

    isolated_store.mark_assessed("s1", "2026-08-30T00:00:00Z")

    # The old ETag no longer matches — a caller polling with it must get the fresh payload,
    # not a stale 304 that would hide the change.
    stale = client.get("/scans/s1", headers={"If-None-Match": old_etag})
    assert stale.status_code == 200
    new_etag = stale.headers["etag"]
    assert new_etag != old_etag
    assert new_etag == 'W/"1"'

    # And the new ETag round-trips to a 304 in its turn.
    fresh = client.get("/scans/s1", headers={"If-None-Match": new_etag})
    assert fresh.status_code == 304


# ── 404s ────────────────────────────────────────────────────────────────────

def test_unknown_scan_404s_even_with_if_none_match(client):
    r = client.get("/scans/never-existed", headers={"If-None-Match": 'W/"0"'})
    assert r.status_code == 404


def test_another_owners_scan_404s_rather_than_304ing(client, isolated_store):
    """A 304 would confirm the scan exists (and at what revision) to a caller who does not own
    it — the same information-leak the plain GET already guards against. Conditional fetch must
    not open a side channel the unconditional path closes."""
    _seed(isolated_store, "s-theirs", owner="someone-else@x")
    r = client.get("/scans/s-theirs", headers={"If-None-Match": 'W/"0"'})
    assert r.status_code == 404
