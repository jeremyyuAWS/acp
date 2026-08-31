"""A dead-lettered scan_folder job leaves the scan unable to ever finish.

Written as a PROBE, before the fix, so the claim would be measured rather than reasoned — the
premise was that the wedge exists, and a probe that passes on unchanged code says it does not.
Both of these failed on unchanged code (`rescue_unfinalized_scans()` returned 0), which is what
earned the fix; store._record_dead_scan_folder is what turns them green. Removing that call
reddens them again.

THE CHAIN. `_scan_folder` calls `increment_completed_folders` only on the success path, and
`rescue_unfinalized_scans` finalizes a per-folder scan only when
`completed_folders >= total_folders`. A folder job that dead-letters returns through neither, so
the counter never reaches the total and nothing can end the run.

This is the SAME failure `_record_dead_scan_files` exists to prevent on the per-file path — its
docstring spells it out ("One expired token mid-run was therefore enough to wedge a whole estate
permanently") — and `_COUNTED_FILE_JOBS` is `("scan_file", "scan_batch")`. 'scan_folder' is not
in it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from conftest import held  # noqa: E402


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "folders.db")
    return store_mod.Store()


def _folder_scan(st, sid, n_folders):
    """A per-folder scan exactly as scan_discover fans one out: total_folders set, one job each."""
    st.init_scan_run(sid, "drive", 0, "2026-08-31T00:00:00Z", "rubric", "hash",
                     owner="demo@example.com", status="running")
    st.set_total_folders(sid, n_folders)
    return [st.enqueue_job("scan_folder", {"scan_id": sid, "folder_id": f"F{i}"}, scan_id=sid)
            for i in range(n_folders)]


def test_a_folder_job_that_dies_still_lets_the_scan_finish(st):
    """Two folders; one succeeds, one exhausts its retries. The scan must still be able to end —
    with the failure recorded — rather than sitting at 'running' with nothing left that could
    ever move it."""
    _folder_scan(st, "s-wedge", 2)

    ok = st.claim_job("w1")
    st.complete_job(ok["id"], **held(st, ok["id"]))
    st.increment_completed_folders("s-wedge")          # what _scan_folder does on success

    bad = st.claim_job("w2")
    assert st.fail_job(bad["id"], "drive 500", force_dead=True, **held(st, bad["id"])) == "dead"

    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT completed_folders, total_folders FROM scan_runs WHERE id=%s",
                       ("s-wedge",))
        row = st._db.fetchone(cur)
    assert row["completed_folders"] >= row["total_folders"], (
        f"the scan is wedged: {row['completed_folders']} of {row['total_folders']} folders "
        "accounted for, and the dead job will never return to increment the rest — "
        "rescue_unfinalized_scans requires completed >= total, so nothing can finalize this run")


def test_the_rescue_sweeper_can_actually_reach_it(st):
    """The end-to-end consequence, stated the way an operator would meet it: after every folder
    job has reached a terminal state, the deploy-safety sweeper must be able to finalize."""
    _folder_scan(st, "s-rescue", 1)
    bad = st.claim_job("w1")
    st.fail_job(bad["id"], "token expired", force_dead=True, **held(st, bad["id"]))

    assert st.rescue_unfinalized_scans() == 1, (
        "rescue_unfinalized_scans could not rescue a scan whose only folder job dead-lettered — "
        "the run stays 'running' forever with no outstanding work")
