"""The scope survives to the reader — which is the whole point of recording it.

Discovery computing a boundary is worth nothing if the boundary does not reach the screen. Both
scan-creation paths write it (the fan-out `init_scan_run` at discover time, and the monolithic
`save_scan` at completion) and both read paths hand it back decoded (`get_scan` and
`list_scans` — the scan-history table reads the latter, and that table is where the 1-vs-8
comparison was made).
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH",
                        Path(tempfile.mkdtemp()) / "scan-scope-test.db")
    return store_mod.Store()


FOLDER_SCOPE = {"kind": "folder", "folder_id": "1W27ULZ", "folder_name": "WCAG Defense Pack",
                "folders_walked": 1, "listed": 1, "kept": 1, "truncated": False}
DRIVE_SCOPE = {"kind": "drive", "raw": 11, "scannable": 8, "kept": 8, "truncated": False}


def _report(sid, files, scope):
    return {
        "_scan_id": sid,
        "rubric": {"name": "r", "version": "1", "hash": "h"},
        "summary": {"files": files, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 50},
        "started_at": "2026-07-30T01:38:35Z", "completed_at": "2026-07-30T01:38:40Z",
        "source": "drive", "scope": scope, "owner": "a@b.c", "files": [],
    }


def test_fanout_discover_path_persists_the_scope_at_discover_time(st):
    """Written at discover, not finalize: the count is on screen from that moment, and a scan
    that dies before finalize is exactly when 'what did this look at?' gets asked."""
    st.init_scan_run("s1", "drive", 1, "2026-07-30T01:38:35Z", "r", "h",
                     owner="a@b.c", status="discovered", scope=FOLDER_SCOPE)
    run = st.get_scan("s1", owner="a@b.c")["run"]
    assert run["scope"] == FOLDER_SCOPE          # an object, not a JSON string
    assert run["scope"]["folder_name"] == "WCAG Defense Pack"


def test_monolithic_save_scan_persists_the_scope(st):
    sid = st.save_scan(_report("s2", 8, DRIVE_SCOPE))
    assert st.get_scan(sid, owner="a@b.c")["run"]["scope"] == DRIVE_SCOPE


def test_scan_history_can_tell_the_two_scans_apart(st):
    """The regression guard, at the layer that rendered the misleading pair.

    list_scans feeds the scan-history table. Before this, both rows were `source='drive'` with a
    file count — 1 above 8 — and nothing else.
    """
    st.save_scan(_report("narrow", 1, FOLDER_SCOPE))
    st.save_scan(_report("wide", 8, DRIVE_SCOPE))
    by_id = {s["id"]: s for s in st.list_scans(owner="a@b.c")}

    assert by_id["narrow"]["scope"]["kind"] == "folder"
    assert by_id["wide"]["scope"]["kind"] == "drive"
    # Same source, different counts — which is precisely why the source column could not carry it.
    assert by_id["narrow"]["source"] == by_id["wide"]["source"] == "drive"
    assert by_id["narrow"]["files"] == 1 and by_id["wide"]["files"] == 8


def test_a_scan_with_no_scope_reads_as_unknown_not_as_whole_drive(st):
    """Every scan already in production predates the column. None of them may be relabelled
    'whole Drive' — defaulting to the reassuring reading is how the defect returns wearing a
    label the reader now trusts."""
    st.init_scan_run("old", "drive", 8, "2026-07-29T18:38:41Z", "r", "h", owner="a@b.c")
    assert st.get_scan("old", owner="a@b.c")["run"]["scope"] is None


def test_unreadable_scope_json_is_unknown_rather_than_an_exception(st):
    """A malformed blob must not take the scan down with it, nor be guessed at."""
    st.init_scan_run("s3", "drive", 1, "2026-07-30T01:38:35Z", "r", "h", owner="a@b.c")
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE scan_runs SET scope=%s WHERE id=%s", ("{not json", "s3"))
    assert st.get_scan("s3", owner="a@b.c")["run"]["scope"] is None


def test_scope_is_decoded_even_when_the_counters_short_circuit_the_aggregate_fill(st):
    """_fill_run_aggregate returns early once certifiable/uncertain/error are all set. The decode
    has to sit BEFORE that return or a finalized scan hands the UI a raw JSON string."""
    sid = st.save_scan(_report("s4", 8, DRIVE_SCOPE))       # save_scan sets all three counters
    run = st.get_scan(sid, owner="a@b.c")["run"]
    assert run["certifiable"] is not None
    assert isinstance(run["scope"], dict)


def test_truncation_survives_the_round_trip(st):
    """The one case where 'it could not see the rest' is literally true has to reach the UI."""
    scope = {"kind": "drive", "raw": 2500, "scannable": 2500, "kept": 500,
             "truncated": True, "cap": 2500}
    sid = st.save_scan(_report("s5", 500, scope))
    assert st.get_scan(sid, owner="a@b.c")["run"]["scope"]["truncated"] is True
