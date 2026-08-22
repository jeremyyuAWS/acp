"""store.list_scans_including_discovered — the narrow fix for the "Assess can't see a
Discover-only estate" bug (found live 2026-08-21).

`list_scans()` filters to `completed_at IS NOT NULL`, which correctly keeps a genuinely
in-flight scan out of the picker — but under ADR 0020 a Discover-only run also never gets a
`completed_at` (it stays `status='discovered'` until Assess runs, possibly forever), so
`list_scans()` cannot tell "still crawling" from "done with discovery, not yet assessed" and
excludes both identically. `list_scans_including_discovered` exists ONLY for the two
api/routes/assess.py callers that need "the latest scan, assessed or not" — it is deliberately
not a drop-in replacement for `list_scans` (see api/store.py's docstring on it for the other
call sites that depend on list_scans' narrower contract: App.jsx's Time-travel detection,
/schedule's "last successful scan", and array-position "previous scan" lookups).
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "devamovate@gmail.com"


def _discovered(store, sid, owner, started_at="2026-08-21T16:00:00+00:00"):
    """A real ADR 0020 Discover-only run — status='discovered', completed_at never set."""
    store.init_scan_run(sid, "drive", 1, started_at, "wcag-aa", "h", owner=owner,
                        status="discovered", scope={"kind": "drive"})


def _assessed(store, sid, owner, completed_at="2026-08-21T17:00:00+00:00"):
    store.init_scan_run(sid, "drive", 1, "2026-08-21T16:00:00+00:00", "wcag-aa", "h", owner=owner,
                        status="running", scope={"kind": "drive"})
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_runs SET completed_at=%s, status='done' WHERE id=%s",
                          (completed_at, sid))


def test_includes_a_discover_only_scan_list_scans_would_hide(isolated_store):
    st = isolated_store
    _discovered(st, "s1", OWNER)
    assert st.list_scans(owner=OWNER) == []                              # the bug, confirmed
    ids = [s["id"] for s in st.list_scans_including_discovered(owner=OWNER)]
    assert ids == ["s1"]                                                 # the fix


def test_an_assessed_scan_still_appears_and_orders_correctly(isolated_store):
    st = isolated_store
    _discovered(st, "s_old", OWNER, started_at="2026-08-18T09:00:00+00:00")
    _assessed(st, "s_new", OWNER, completed_at="2026-08-21T10:00:00+00:00")
    ids = [s["id"] for s in st.list_scans_including_discovered(owner=OWNER)]
    assert ids == ["s_new", "s_old"]   # COALESCE(completed_at, discovered_at, started_at) DESC


def test_owner_scoped(isolated_store):
    st = isolated_store
    _discovered(st, "mine", OWNER)
    _discovered(st, "theirs", OTHER)
    ids = [s["id"] for s in st.list_scans_including_discovered(owner=OWNER)]
    assert ids == ["mine"]


def test_empty_without_any_scans(isolated_store):
    assert isolated_store.list_scans_including_discovered(owner=OWNER) == []


def test_rows_have_scope_decoded_to_a_dict_like_list_scans(isolated_store):
    """Callers (api/routes/assess.py) read `s.get("scope")` expecting a dict, not a JSON string —
    same contract list_scans already provides via _fill_run_aggregate."""
    st = isolated_store
    _discovered(st, "s1", OWNER)
    row = st.list_scans_including_discovered(owner=OWNER)[0]
    assert isinstance(row["scope"], dict)
    assert row["scope"]["kind"] == "drive"


def test_never_double_counts_certifiable_uncertain_error_as_none(isolated_store):
    """A discover-only scan has no file_records yet — _fill_run_aggregate must still return 0s,
    not None, for the three counters (same guarantee list_scans already gives its callers)."""
    st = isolated_store
    _discovered(st, "s1", OWNER)
    row = st.list_scans_including_discovered(owner=OWNER)[0]
    for k in ("certifiable", "uncertain", "error"):
        assert row[k] == 0
