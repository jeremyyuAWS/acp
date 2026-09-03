from __future__ import annotations


def _scan(owner="admin@example.org"):
    return {
        "_scan_id": "scan-live-1", "owner": owner, "source": "drive",
        "started_at": "2026-09-03T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 2, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    }


def test_admin_live_activity_groups_active_stage_without_exposing_payload(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Private Report.docx", "secret": "never-return"},
                               scan_id="scan-live-1")
    rows = isolated_store.admin_live_activity()
    assert len(rows) == 1
    assert rows[0]["stage"] == "assess"
    assert rows[0]["owner"] == "admin@example.org"
    assert rows[0]["queued"] == 1
    assert "payload" not in rows[0]
    assert "secret" not in str(rows[0])


def test_admin_live_activity_omits_inactive_runs(isolated_store):
    isolated_store.save_scan(_scan())
    job_id = isolated_store.enqueue_job("scan_file", {"file": "done.docx"}, scan_id="scan-live-1")
    claimed = isolated_store.claim_job("test-worker")
    assert claimed and claimed["id"] == job_id
    isolated_store.complete_job(job_id, worker_id="test-worker", attempt=claimed["attempts"])
    assert isolated_store.admin_live_activity() == []
