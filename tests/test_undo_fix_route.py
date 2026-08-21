"""POST /scans/{sid}/files/{filename}/undo-fix — R15, the route half.

The store method (test_remediation_diff_store.py) proves what gets cleared; this proves the
route is reachable, owner-scoped like every other per-scan route, and returns the shape the
frontend reads (`{"undone": bool}`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "devamovate@gmail.com"


def _seed_scan(store, sid: str, owner: str) -> None:
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-08-21T05:00:00+00:00",
        "completed_at": "2026-08-21T05:05:00+00:00",
        "source": "drive",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 90},
        "files": [{"file": "handbook.docx", "engine": ".net/office", "status": "certifiable",
                   "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}],
    })


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_foreign_scan_404.py's fixture — see that file for why."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, OTHER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_owner_can_undo_an_applied_fix(gated_client, isolated_store):
    _seed_scan(isolated_store, "s-undo1", OWNER)
    isolated_store.record_remediation_diffs("s-undo1", "handbook.docx",
        [{"rule_id": "1.1.1", "before": "(no alt)", "after": "A red barn"}])

    r = gated_client(OWNER).post("/scans/s-undo1/files/handbook.docx/undo-fix",
                                  json={"rule_id": "1.1.1"})
    assert r.status_code == 200
    assert r.json() == {"undone": True}
    assert isolated_store.get_remediation_diffs("s-undo1", "handbook.docx") == []


def test_undoing_a_fix_never_applied_returns_undone_false_not_an_error(gated_client, isolated_store):
    _seed_scan(isolated_store, "s-undo2", OWNER)
    r = gated_client(OWNER).post("/scans/s-undo2/files/handbook.docx/undo-fix",
                                  json={"rule_id": "9.9.9"})
    assert r.status_code == 200
    assert r.json() == {"undone": False}


def test_missing_rule_id_is_a_400_not_a_silent_no_op(gated_client, isolated_store):
    _seed_scan(isolated_store, "s-undo3", OWNER)
    r = gated_client(OWNER).post("/scans/s-undo3/files/handbook.docx/undo-fix", json={})
    assert r.status_code == 400


def test_a_non_owner_gets_404_not_someone_elses_undo(gated_client, isolated_store):
    _seed_scan(isolated_store, "s-undo4", OWNER)
    isolated_store.record_remediation_diffs("s-undo4", "handbook.docx",
        [{"rule_id": "1.1.1", "before": "a", "after": "b"}])

    r = gated_client(OTHER).post("/scans/s-undo4/files/handbook.docx/undo-fix",
                                  json={"rule_id": "1.1.1"})
    assert r.status_code == 404
    # And the fix is still there — a 404 has to mean nothing happened, not "happened invisibly".
    assert isolated_store.get_remediation_diffs("s-undo4", "handbook.docx") != []
