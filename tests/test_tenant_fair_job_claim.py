"""Tenant-fair durable queue selection for competing Assess/Remediate fan-outs."""
from __future__ import annotations

from conftest import held


def _scan(scan_id: str, owner: str) -> dict:
    return {
        "_scan_id": scan_id, "owner": owner, "source": "drive",
        "started_at": "2026-09-03T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 2, "certifiable": 0, "uncertain": 0, "error": 0,
                    "avg_score": 0},
        "files": [],
    }


def _seed(st):
    st.save_scan(_scan("scan-a", "a@example.org"))
    st.save_scan(_scan("scan-b", "b@example.org"))
    a = [st.enqueue_job("scan_file", {"file": f"a{i}.docx"}, scan_id="scan-a")
         for i in range(2)]
    b = [st.enqueue_job("scan_file", {"file": f"b{i}.docx"}, scan_id="scan-b")
         for i in range(2)]
    return a, b


def test_competing_tenants_receive_alternating_capacity(isolated_store):
    a, b = _seed(isolated_store)
    first = isolated_store.claim_job("w1")
    second = isolated_store.claim_job("w2")
    assert first["id"] == a[0]
    assert second["id"] == b[0], "tenant B must not wait behind tenant A's whole fan-out"

    isolated_store.complete_job(first["id"], **held(isolated_store, first["id"]))
    isolated_store.complete_job(second["id"], **held(isolated_store, second["id"]))
    third = isolated_store.claim_job("w1")
    fourth = isolated_store.claim_job("w2")
    assert [third["id"], fourth["id"]] == [a[1], b[1]]


def test_a_single_tenant_can_use_all_available_slots(isolated_store):
    isolated_store.save_scan(_scan("scan-a", "a@example.org"))
    jobs = [isolated_store.enqueue_job("scan_file", {"file": str(i)}, scan_id="scan-a")
            for i in range(2)]
    assert [isolated_store.claim_job("w1")["id"], isolated_store.claim_job("w2")["id"]] == jobs


def test_priority_still_precedes_tenant_fairness(isolated_store):
    isolated_store.save_scan(_scan("scan-a", "a@example.org"))
    isolated_store.save_scan(_scan("scan-b", "b@example.org"))
    high = [isolated_store.enqueue_job("scan_file", {"file": str(i)}, priority=10,
                                       scan_id="scan-a") for i in range(2)]
    isolated_store.enqueue_job("scan_file", {"file": "b"}, priority=100, scan_id="scan-b")
    assert isolated_store.claim_job("w1")["id"] == high[0]
    assert isolated_store.claim_job("w2")["id"] == high[1]


def test_dedicated_lane_counts_only_compatible_tenant_work(isolated_store):
    isolated_store.save_scan(_scan("scan-a", "a@example.org"))
    isolated_store.save_scan(_scan("scan-b", "b@example.org"))
    isolated_store.enqueue_job("remediate_file", {"file": "fix.docx"}, scan_id="scan-a")
    assert isolated_store.claim_job("remediate", job_types=("remediate_file",))
    first_assess = isolated_store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="scan-a")
    isolated_store.enqueue_job("scan_file", {"file": "b.docx"}, scan_id="scan-b")

    claimed = isolated_store.claim_job("assess", job_types=("scan_file",))
    assert claimed["id"] == first_assess, "another worker lane must not consume this lane's fair share"
