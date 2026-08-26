"""GET /scans/{scan_id}/discover/stream falls back to the durable Postgres checkpoint
(core.py's _maybe_checkpoint, store.checkpoint_scan_progress) when Redis has no live job state
for the scan at all — a caller should see "last known state" instead of nothing when Redis is
unreachable, a job's key TTL'd out, or a no-Redis replica's in-memory JOBS isn't visible here.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"


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
    # No job is ever claimed for this scan in these tests — get_job_id_for_scan must return
    # None so the stream falls all the way through to the checkpoint fallback.
    monkeypatch.setattr(core, "get_job_id_for_scan", lambda scan_id: None)

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_falls_back_to_the_checkpoint_when_no_live_job_exists(gated_client, isolated_store):
    isolated_store.init_scan_run("s-fallback1", "drive", total=10,
                                 started_at=datetime.now(timezone.utc).isoformat(),
                                 rubric_name="r", rubric_hash="h", owner=OWNER, status="running")
    at = datetime.now(timezone.utc).isoformat()
    isolated_store.checkpoint_scan_progress(
        "s-fallback1", {"phase": "lifecycle", "files_evaluated": 40}, at)

    with gated_client(OWNER).stream("GET", "/scans/s-fallback1/discover/stream") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())

    assert '"phase": "lifecycle"' in body or '"phase":"lifecycle"' in body
    assert '"files_evaluated": 40' in body or '"files_evaluated":40' in body
    assert '"live": false' in body or '"live":false' in body
    assert "event: error" in body   # still ends in the same terminal error as before


def test_no_checkpoint_frame_when_there_is_no_checkpoint_either(gated_client, isolated_store):
    """A scan that never got far enough to checkpoint (or predates this feature) must not
    fabricate one — just the plain terminal error, same as before this change."""
    isolated_store.init_scan_run("s-fallback2", "drive", total=1,
                                 started_at=datetime.now(timezone.utc).isoformat(),
                                 rubric_name="r", rubric_hash="h", owner=OWNER, status="running")

    with gated_client(OWNER).stream("GET", "/scans/s-fallback2/discover/stream") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())

    assert '"live"' not in body
    assert "event: error" in body
