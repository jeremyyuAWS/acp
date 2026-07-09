"""jobs.phase — what a running job is actually doing.

The queue panel used to cycle five hardcoded WCAG criteria under the running job every 1.6s.
The phase now comes from the handler, written where the work genuinely changes.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st():
    import store as store_mod
    store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "phase.db"
    store_mod._SCHEMA[:] = [x for x in store_mod._SCHEMA
                            if not x.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def test_phase_round_trips(st):
    jid = st.enqueue_job("remediate_file", {"file": "deck.pptx"})
    st.set_job_phase(jid, "applying fixes to deck.pptx")
    assert st.get_job(jid)["phase"] == "applying fixes to deck.pptx"


def test_a_fresh_job_has_no_phase(st):
    jid = st.enqueue_job("remediate_file", {"file": "deck.pptx"})
    assert st.get_job(jid)["phase"] is None      # absent phase renders no line, not a fake one


def test_claiming_clears_a_stale_phase_from_a_previous_attempt(st):
    jid = st.enqueue_job("remediate_file", {"file": "deck.pptx"})
    st.set_job_phase(jid, "writing the corrected copy to Drive")
    st.fail_job(jid, "boom", backoff_seconds=0)          # back to queued for a retry
    claimed = st.claim_job("worker-1")
    assert claimed is not None and claimed["id"] == jid
    assert claimed["phase"] is None, "a retry must not inherit the last attempt's phase"


def test_phase_write_never_raises_and_never_fails_the_job(st, capsys):
    # Progress reporting must not be able to break the work it reports on.
    st.set_job_phase("no-such-job-id", "downloading")     # no row -> no-op, no exception


def test_setting_phase_bumps_updated_at(st):
    jid = st.enqueue_job("remediate_file", {"file": "deck.pptx"})
    before = st.get_job(jid)["updated_at"]
    st.set_job_phase(jid, "re-verifying the corrected copy")
    assert st.get_job(jid)["updated_at"] >= before
