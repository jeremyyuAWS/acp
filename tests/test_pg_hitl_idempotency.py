"""Production-engine concurrency coverage for HITL request idempotency."""
from __future__ import annotations

import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store as store_mod  # noqa: E402

_PG = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _PG.startswith("postgres"), reason="needs the disposable PostgreSQL integration job")


def test_concurrent_duplicate_decision_commits_once():
    st = store_mod.Store()
    scan_id = f"hitl-idempotency-{uuid.uuid4()}"
    st.init_scan_run(scan_id, "drive", 1, "t0", "rubric", "hash")
    item_id = st.enqueue_proposals(scan_id, "deck.pptx", "1.1.1", [{
        "locator": "ppt/slides/slide1.xml#Picture 1",
        "proposed_value": "A quarterly revenue chart.",
    }])
    barrier = threading.Barrier(2)

    def decide():
        barrier.wait()
        return st.complete_hitl_decision(
            item_id, "approved", None, None,
            resolution=None, approved_values=["A quarterly revenue chart."],
            actor="reviewer@example.com", detail=None,
            request_id="same-transport-request", expected_version=0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(decide), pool.submit(decide)]]

    assert sorted(replayed for _row, replayed in results) == [False, True]
    row = st.get_hitl_item(item_id)
    assert row["decision_version"] == 1
    assert [d["action"] for d in st.list_decisions(scan_id)] == ["hitl.approved"]
    assert [j["type"] for j in st.list_jobs() if j.get("scan_id") == scan_id] == [
        "apply_approved_values"]
