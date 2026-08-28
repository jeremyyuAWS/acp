"""store.list_finished_scans — the narrow fix for the "/monitor/estate can't see a Discover-only
estate" bug (found live 2026-08-28), the same shape of blind spot list_scans_including_discovered
already fixed for api/routes/assess.py's eligibility preview on 2026-08-21.

`list_scans()` filters to `completed_at IS NOT NULL`, which an ADR 0020 Discover-only run never
sets — it stays `status='discovered'` with only `discovered_at` stamped, possibly forever, until
someone runs Assess. A caller using list_scans() cannot tell "still crawling" from "done with
discovery, never assessed" and excludes both identically — which is exactly what made
/monitor/estate's "did the newest scan collapse" check permanently blind to every Discover-only
run: its "newest scan" was whatever full-analysis scan happened to predate ADR 0020 becoming the
default, stale on any deployment where Discover-only is now the common case.

list_scans_including_discovered() already exists but is deliberately too wide for THIS need: it
also includes 'running'/'queued' scans (falling back to started_at when neither timestamp is
set), so a scan that started 2 seconds ago and has not listed a single file yet would outrank a
real, finished 5,000-document scan as "the newest" — reintroducing the identical dishonest-zero
shape server-side that DiscoverRunProgress.jsx fights on the frontend. list_finished_scans() is
the precise middle ground: completed_at OR discovered_at, nothing still in-flight.
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "devamovate@gmail.com"


def _discovered(store, sid, owner, files=5, started_at="2026-08-28T16:00:00+00:00",
                discovered_at=None):
    """A real ADR 0020 Discover-only run: status='discovered', discovered_at set.

    set_scan_status(sid, "discovered") is the only production code path that stamps
    discovered_at (init_scan_run alone does not, even when passed status='discovered' directly)
    — but it always stamps the REAL current wall-clock time, which is fine for production and
    wrong for a test that wants a specific, controllable ordering. Use set_scan_status when
    discovered_at is left unset (proves the real stamping path works); write it directly via SQL
    when a specific past instant is needed for an ordering assertion."""
    store.init_scan_run(sid, "drive", files, started_at, "wcag-aa", "h", owner=owner,
                        status="running", scope={"kind": "drive"})
    store.set_scan_files(sid, files)
    if discovered_at is None:
        store.set_scan_status(sid, "discovered")
    else:
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE scan_runs SET status='discovered', discovered_at=%s WHERE id=%s",
                              (discovered_at, sid))


def _still_running(store, sid, owner, files=0, started_at="2026-08-28T16:30:00+00:00"):
    """A scan mid-listing — neither completed_at nor discovered_at set yet."""
    store.init_scan_run(sid, "drive", files, started_at, "wcag-aa", "h", owner=owner,
                        status="running", scope={"kind": "drive"})


def _assessed(store, sid, owner, files=5, completed_at="2026-08-28T17:00:00+00:00"):
    store.init_scan_run(sid, "drive", files, "2026-08-28T16:00:00+00:00", "wcag-aa", "h",
                        owner=owner, status="running", scope={"kind": "drive"})
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_runs SET completed_at=%s, status='done' WHERE id=%s",
                          (completed_at, sid))


def _failed(store, sid, owner, started_at="2026-08-28T16:00:00+00:00"):
    store.init_scan_run(sid, "drive", 0, started_at, "wcag-aa", "h", owner=owner,
                        status="running", scope={"kind": "drive"})
    store.set_scan_status(sid, "failed")


def test_includes_a_discover_only_scan_list_scans_would_hide(isolated_store):
    st = isolated_store
    _discovered(st, "s1", OWNER)
    assert st.list_scans(owner=OWNER) == []                              # the bug, confirmed
    ids = [s["id"] for s in st.list_finished_scans(owner=OWNER)]
    assert ids == ["s1"]                                                 # the fix


def test_excludes_a_scan_still_in_flight_unlike_list_scans_including_discovered(isolated_store):
    """The precise difference from list_scans_including_discovered: a fresh, still-listing scan
    must not outrank a real finished one just because it started more recently."""
    st = isolated_store
    _discovered(st, "s_old", OWNER, files=5000, started_at="2026-08-20T09:00:00+00:00",
               discovered_at="2026-08-20T09:05:00+00:00")
    _still_running(st, "s_new", OWNER, files=0, started_at="2026-08-28T23:59:00+00:00")

    # The wider method WOULD be fooled by this — pinning that as documented behaviour, not a bug.
    wide_ids = [s["id"] for s in st.list_scans_including_discovered(owner=OWNER)]
    assert wide_ids == ["s_new", "s_old"]

    finished_ids = [s["id"] for s in st.list_finished_scans(owner=OWNER)]
    assert finished_ids == ["s_old"]


def test_excludes_a_failed_scan(isolated_store):
    """A failed attempt never reaches _mark_discovered, so discovered_at stays NULL — it has no
    real data to compare and must not read as "the newest" with a false zero."""
    st = isolated_store
    _discovered(st, "s_old", OWNER, files=5, started_at="2026-08-20T09:00:00+00:00",
               discovered_at="2026-08-20T09:05:00+00:00")
    _failed(st, "s_failed", OWNER, started_at="2026-08-28T23:59:00+00:00")
    ids = [s["id"] for s in st.list_finished_scans(owner=OWNER)]
    assert ids == ["s_old"]


def test_an_assessed_scan_still_appears_and_orders_correctly(isolated_store):
    st = isolated_store
    _discovered(st, "s_old", OWNER, started_at="2026-08-18T09:00:00+00:00",
               discovered_at="2026-08-18T09:05:00+00:00")
    _assessed(st, "s_new", OWNER, completed_at="2026-08-21T10:00:00+00:00")
    ids = [s["id"] for s in st.list_finished_scans(owner=OWNER)]
    assert ids == ["s_new", "s_old"]   # COALESCE(completed_at, discovered_at) DESC


def test_owner_scoped(isolated_store):
    st = isolated_store
    _discovered(st, "mine", OWNER)
    _discovered(st, "theirs", OTHER)
    ids = [s["id"] for s in st.list_finished_scans(owner=OWNER)]
    assert ids == ["mine"]


def test_owner_agnostic_when_owner_is_none_like_the_monitor_wants(isolated_store):
    st = isolated_store
    _discovered(st, "mine", OWNER)
    _discovered(st, "theirs", OTHER)
    ids = {s["id"] for s in st.list_finished_scans()}
    assert ids == {"mine", "theirs"}


def test_empty_without_any_scans(isolated_store):
    assert isolated_store.list_finished_scans(owner=OWNER) == []


def test_rows_have_scope_decoded_to_a_dict(isolated_store):
    st = isolated_store
    _discovered(st, "s1", OWNER)
    row = st.list_finished_scans(owner=OWNER)[0]
    assert isinstance(row["scope"], dict)
    assert row["scope"]["kind"] == "drive"


def test_never_double_counts_certifiable_uncertain_error_as_none(isolated_store):
    """A discover-only scan has no file_records yet — _fill_run_aggregate must still return 0s,
    not None, for the three counters (same guarantee list_scans already gives its callers)."""
    st = isolated_store
    _discovered(st, "s1", OWNER)
    row = st.list_finished_scans(owner=OWNER)[0]
    for k in ("certifiable", "uncertain", "error"):
        assert row[k] == 0


def test_files_reflects_the_real_discovered_count(isolated_store):
    """The whole point: the count the monitor's collapse check compares must be real."""
    st = isolated_store
    _discovered(st, "s1", OWNER, files=6922)
    row = st.list_finished_scans(owner=OWNER)[0]
    assert row["files"] == 6922
