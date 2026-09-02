from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def test_local_assessed_file_can_enter_remediation_without_a_drive_id(client, isolated_store):
    isolated_store.save_scan({
        "_scan_id": "local-1", "started_at": "2026-09-02T00:00:00Z",
        "completed_at": "2026-09-02T00:01:00Z", "source": "local", "owner": "demo",
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 0, "uncertain": 1, "error": 0, "avg_score": 50},
        "files": [{"file": "a.docx", "engine": "office", "status": "uncertain", "score": 50,
                   "compliant": 0, "skipped_rules": 0,
                   "issues": [{"ruleId": "DOC_TITLE", "wcag": "2.4.2", "severity": "SERIOUS"}]}],
    })

    r = client.post("/scans/local-1/remediate", json={"scope": ["a.docx"]})
    assert r.status_code == 200
    assert r.json()["enqueued"] == 1
    job = isolated_store.get_job(r.json()["job_ids"][0])
    assert job["payload"]["source"] == "local"
    assert job["payload"]["owner"] == "demo"
