"""The BOUNDARY a multi-site SharePoint scan covered, and the two places it is compared.

A file count is not a fact about an estate — it is a fact about a boundary the caller chose.
For SharePoint that boundary used to be one site id, and both comparisons keyed off that single
field. A multi-site run has no singular `site`, so both would have read None on every multi-site
scan and matched them all to each other:

  * last_published_whole_source_baseline — the incremental / collapse-guard baseline. A run
    covering Finance+HR would have been compared against one covering Legal+Ops, and the
    difference reported as the estate shrinking.
  * get_inventory_diff's `_boundary` — decides whether a file absent from the newer run may be
    called REMOVED. Two different site sets read as the same boundary means "gone from
    SharePoint" said about a document that was never in scope.

store.sharepoint_scope_sites is the one key both now use.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402

sites = store_mod.sharepoint_scope_sites


# ── the key itself ───────────────────────────────────────────────────────────────────────────

def test_the_key_is_order_independent():
    """Two operators picking the same two sites in a different order chose the same boundary."""
    assert sites({"sites": [{"id": "S1"}, {"id": "S2"}]}) == \
           sites({"sites": [{"id": "S2"}, {"id": "S1"}]})


def test_different_site_sets_are_different_boundaries():
    assert sites({"sites": [{"id": "S1"}, {"id": "S2"}]}) != sites({"sites": [{"id": "S1"}]})
    assert sites({"sites": [{"id": "S1"}]}) != sites({"sites": [{"id": "S2"}]})


def test_a_pre_multi_site_scan_still_keys_off_its_single_site():
    """Every SharePoint run recorded before `sites` existed carries only `site`. Without this
    fallback they would all key to () — the boundary check silently disabled across the change,
    which is worse than no check at all because nothing about it looks different.
    """
    assert sites({"site": "S1"}) == ("S1",)
    assert sites({"site": "S1"}) == sites({"sites": [{"id": "S1"}]}), \
        "the two spellings of ONE site must be the same boundary"


def test_onedrive_and_non_sharepoint_scopes_key_to_empty():
    assert sites({"kind": "sharepoint", "site": None}) == ()
    assert sites({"kind": "drive", "folder": "f1"}) == ()
    assert sites(None) == ()


def test_a_bare_string_site_list_is_accepted():
    """Defensive: scope blobs are JSON read back from the database, and a future writer handing
    plain ids must not make the comparison throw mid-scan."""
    assert sites({"sites": ["S2", "S1"]}) == ("S1", "S2")


# ── the baseline comparison ──────────────────────────────────────────────────────────────────

def _sp_run(store, sid, at, scope, *, owner="owner@example.com", files=2):
    store.init_scan_run(sid, "sharepoint", 0, at, "rb", "h", owner=owner, status="running",
                        scope={**scope, "kind": "sharepoint",
                               "enumeration": {"complete": True, "truncated": False}})
    store.add_inventory(sid, [{"file": f"f{i}.pdf"} for i in range(files)])
    store.mark_published(sid, at=at)


def test_a_baseline_from_a_different_site_set_is_not_used(isolated_store):
    """Finance+HR compared against Legal+Ops is not an estate that shrank; it is two different
    estates. Before this both keyed to `site: None` and matched."""
    s = isolated_store
    _sp_run(s, "old", "2026-01-01T00:00:00Z", {"sites": [{"id": "Legal"}, {"id": "Ops"}]})
    s.init_scan_run("new", "sharepoint", 0, "2026-02-01T00:00:00Z", "rb", "h",
                    owner="owner@example.com", status="running")
    assert s.last_published_whole_source_baseline(
        "new", owner="owner@example.com",
        current_scope={"kind": "sharepoint", "sites": [{"id": "Finance"}, {"id": "HR"}]}) is None


def test_a_baseline_covering_the_same_sites_in_another_order_is_used(isolated_store):
    s = isolated_store
    _sp_run(s, "old", "2026-01-01T00:00:00Z", {"sites": [{"id": "Finance"}, {"id": "HR"}]})
    s.init_scan_run("new", "sharepoint", 0, "2026-02-01T00:00:00Z", "rb", "h",
                    owner="owner@example.com", status="running")
    found = s.last_published_whole_source_baseline(
        "new", owner="owner@example.com",
        current_scope={"kind": "sharepoint", "sites": [{"id": "HR"}, {"id": "Finance"}]})
    assert found is not None and found["scan_id"] == "old" and found["count"] == 2


def test_a_single_site_baseline_still_matches_its_own_site(isolated_store):
    """The pre-existing behaviour, unchanged: one site, recorded the old way, matched by a run
    covering that same site."""
    s = isolated_store
    _sp_run(s, "old", "2026-01-01T00:00:00Z", {"site": "Finance"})
    s.init_scan_run("new", "sharepoint", 0, "2026-02-01T00:00:00Z", "rb", "h",
                    owner="owner@example.com", status="running")
    found = s.last_published_whole_source_baseline(
        "new", owner="owner@example.com",
        current_scope={"kind": "sharepoint", "site": "Finance"})
    assert found is not None and found["scan_id"] == "old"

    s.init_scan_run("other", "sharepoint", 0, "2026-03-01T00:00:00Z", "rb", "h",
                    owner="owner@example.com", status="running")
    assert s.last_published_whole_source_baseline(
        "other", owner="owner@example.com",
        current_scope={"kind": "sharepoint", "site": "Legal"}) is None
