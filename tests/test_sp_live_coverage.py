"""SharePoint coverage on the operations map — and the store-shape bug that nearly shipped.

A 30-site walk is one long "discovering" bar on Live Operations: the file count ticks up and
nothing says which sites are done, which are still queued, or that one is blocked on a consent
that lapsed this morning. The per-site report is already checkpointed on the run (the listing's
own progress patches accumulate into scan_runs.live_checkpoint), so surfacing it is a read of
something already written rather than new instrumentation.

WHY THIS FILE ALSO ASSERTS THAT A METHOD EXISTS. Adding `_sp_coverage` as a module-level function
in the middle of the class body did not fail to parse — it nested `admin_live_activity` INSIDE it,
so `Store.admin_live_activity` silently stopped existing while `python -c "import ast"` reported
the file was fine. A syntax check is not a correctness check, and the only reason it was caught
was an explicit `hasattr`. That assertion is now permanent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import store  # noqa: E402


def _cp(sites):
    return json.dumps({"phase": "discovering", "files_found": 12, "sites": sites})


def test_the_live_activity_method_is_still_a_method():
    """The guard the class-nesting bug needed. A def at column 0 inserted into a class body ends
    the class and adopts everything after it — legal Python, catastrophic semantics, and invisible
    to a parse check."""
    assert hasattr(store.Store, "admin_live_activity")
    assert callable(store.Store.admin_live_activity)


def test_a_run_with_no_site_data_reports_NOTHING_rather_than_zeros():
    """A Drive scan, a OneDrive run, a SharePoint scan that has not reached its first site.
    "0 of 0 sites" on every non-SharePoint run is a fact about the map, not about the estate."""
    assert store._sp_coverage(None) == {}
    assert store._sp_coverage("") == {}
    assert store._sp_coverage(_cp([])) == {}
    assert store._sp_coverage(json.dumps({"phase": "discovering"})) == {}


def test_it_counts_sites_done_unread_and_libraries():
    got = store._sp_coverage(_cp([
        {"id": "S1", "status": "complete", "libraries": [{"id": "d1"}, {"id": "d2"}]},
        {"id": "S2", "status": "scanning", "libraries": [{"id": "d3"}]},
        {"id": "S3", "status": "blocked", "libraries": []},
        {"id": "S4", "status": "skipped", "libraries": []},
    ]))
    assert got == {"sites_total": 4, "sites_done": 1, "sites_unread": 2, "libraries_total": 3}


def test_blocked_and_skipped_are_counted_together_as_not_read():
    """On this screen the operator is asking how much of the estate is covered, and both answer
    "not this bit". WHICH of the two, and why, is the exception report's job."""
    got = store._sp_coverage(_cp([{"id": "A", "status": "blocked"},
                                  {"id": "B", "status": "skipped"}]))
    assert got["sites_unread"] == 2


def test_a_checkpoint_already_decoded_to_a_dict_is_accepted():
    """The column comes back as text on one adapter and a dict on another; a reader that handled
    one would show no coverage at all on the other."""
    got = store._sp_coverage({"sites": [{"id": "S1", "status": "complete"}]})
    assert got["sites_total"] == 1


@pytest.mark.parametrize("bad", ["not json", "[1,2,3]", '{"sites": "nonsense"}',
                                 '{"sites": [1, null]}'])
def test_a_malformed_checkpoint_costs_the_counts_and_never_the_map(bad):
    """This blob is written by a worker and read by an admin screen. One written in a shape this
    code does not expect must cost the coverage counts, never the operations map."""
    assert store._sp_coverage(bad) == {} or "sites_total" in store._sp_coverage(bad)


def test_the_query_actually_selects_the_checkpoint_column():
    """The one-name omission this repo has already paid for twice (TODO P1e, and Phase 1's
    site_id). A derivation that reads a column the query never selects returns nothing, forever,
    and looks exactly like an estate with no sites."""
    import inspect
    src = inspect.getsource(store.Store.admin_live_activity)
    assert "sr.live_checkpoint" in src
    assert "_sp_coverage(row.get(\"live_checkpoint\"))" in src
