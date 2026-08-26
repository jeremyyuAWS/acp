"""GET /scans/{scan_id}/discover/stream had no ownership check at all when it shipped (#840) —
any authenticated user who had (or guessed) a scan_id could stream someone else's live discovery
progress: file counts, phase, lifecycle match/tag/archive/delete stats. Every other /scans/*
route in this file scopes to the requester via _owner(request) + get_scan(..., owner=...); this
one didn't. Same fix, same 404-not-403 reasoning as GET /scans/{sid} — a scan id must not work as
an existence oracle across accounts.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "other@example.com"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_cancel_queued_job.py's fixture."""
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


def test_a_stranger_cannot_stream_someone_elses_scan(gated_client, isolated_store):
    scan_id, job_id = isolated_store.enqueue_scan("s-stream1", "drive", OWNER, "scan_discover", {})
    r = gated_client(OTHER).get(f"/scans/{scan_id}/discover/stream")
    assert r.status_code == 404


def test_an_unknown_scan_id_also_404s_rather_than_hanging(gated_client):
    r = gated_client(OWNER).get("/scans/does-not-exist/discover/stream")
    assert r.status_code == 404


def test_the_owner_can_open_their_own_stream(gated_client, isolated_store):
    scan_id, job_id = isolated_store.enqueue_scan("s-stream2", "drive", OWNER, "scan_discover", {})
    with gated_client(OWNER).stream("GET", f"/scans/{scan_id}/discover/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
