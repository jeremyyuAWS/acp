"""A SharePoint scan that died mid-listing resumes from its last completed site (Phase 4).

THE COST THIS REMOVES. Discovery persisted its inventory in one write after the LAST site, so a
thirty-site estate that died at site twenty-eight discarded twenty-eight sites' worth of Graph
calls and began again at site one. The larger the tenant the longer the run, the likelier the
interruption, and the more each one cost — exactly inverted.

THE PART THAT IS NOT OBVIOUS, and the reason this file exists beside the scanner's own
tests/test_sp_checkpoint.py: a naive resume is WORSE THAN NO RESUME. Two handler-side guards read
the listing as if it were the whole estate.

  * `count_inventory(scan_id) > 0` used to mean one thing — "a previous attempt listed everything
    and died afterwards" — and the checkpoint-resume path skips the listing entirely on the
    strength of it. Per-site checkpoints put rows in that table MID-listing. Without the
    `listing_complete` marker, a scan that died at site 3 resumes by declaring three sites the
    whole estate and publishing it.
  * The scope-collapse guard compares this run's count against the last published whole-source
    scan. A resumed run lists only the sites it has left, so 30 sites minus 28 already persisted
    arrives looking exactly like the permissions collapse the guard exists to catch — and the
    guard FAILS AND BLOCKS the scan, with a message telling the operator to check access that is
    not the problem. A wrong diagnosis is worse than a slow re-listing.

Both are pinned below, and both are asserted at the level that fails when the guard is removed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OWNER = "admin@x.com"


def _doc(site: str, n: int) -> dict:
    """One scanner listing item as _sp_classify_item builds it for a site walk."""
    return {"name": f"{site}-{n}.docx", "id": f"{site}-i{n}", "mime": DOCX, "source_mime": DOCX,
            "path": f"/{site}/{site}-{n}.docx", "parent_folder": f"/{site}", "owner": OWNER,
            "created_at": "2024-01-01T00:00:00+00:00",
            "source_modified": "2024-02-01T00:00:00+00:00",
            "size_kb": 11, "checksum": f"c-{site}-{n}",
            "siteId": site, "siteName": site, "libraryName": "Documents",
            "driveId": f"d-{site}"}


class _Tenant:
    """A stand-in for the SharePoint listing that walks `sites` in order, `per_site` documents
    each, and DIES after `die_after` sites — the interruption this whole feature is about.

    It honours `sp_skip_sites` and calls `sp_site_done` exactly as scanner._sp_list does, which is
    what makes it a fair stand-in: the scanner's own contract is pinned separately in
    tests/test_sp_checkpoint.py, so what is under test here is only what the handler does with it.
    """

    def __init__(self, sites, per_site=2, die_after=None):
        self.sites, self.per_site, self.die_after = sites, per_site, die_after
        self.walked: list[str] = []

    def __call__(self, source, svc=None, **kw):
        scope_out = kw.get("scope_out")
        done = kw.get("sp_site_done")
        skip = kw.get("sp_skip_sites") or {}
        out, report = [], []
        for s in self.sites:
            if s in skip:
                # The dict form: a skipped site is reported with the counts the CALLER supplied,
                # exactly as _sp_list does — see tests/test_sp_checkpoint.py, which pins that
                # contract against the real scanner.
                known = skip[s] if isinstance(skip, dict) else {}
                report.append({"id": s, "status": "complete", "resumed": True, "libraries": [],
                               "listed": int(known.get("listed") or 0),
                               "estate": int(known.get("estate") or 0)})
                continue
            if self.die_after is not None and len(self.walked) >= self.die_after:
                raise RuntimeError("worker died mid-listing")
            self.walked.append(s)
            mine = [_doc(s, n) for n in range(self.per_site)]
            out.extend(mine)
            report.append({"id": s, "status": "complete", "libraries": [],
                           "listed": len(mine), "estate": len(mine)})
            if done:
                done(s, mine, [])
        if scope_out is not None:
            scope_out.update({"kind": "sharepoint", "sites": report, "truncated": False,
                              "enumeration": {"complete": True}})
        return out


def _wire(monkeypatch, st, tenant):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    # `scanner._list`, not `handlers._list`: the handler imports it inside the function, so the
    # name it resolves is the scanner module's.
    monkeypatch.setattr(scanner, "_list", tenant)
    # The delta planner reads the store for cursors; irrelevant here and it would only add noise
    # to what each attempt lists.
    monkeypatch.setattr(handlers, "_sp_site_delta_plan", lambda *a, **k: None)


def _discover(scan_id: str):
    import handlers
    handlers._scan_discover(
        {"scan_id": scan_id, "source": "sharepoint", "user": OWNER, "sp_token": "tok"},
        {"scan_id": scan_id})


def _checkpoint(st, scan_id) -> dict:
    scope = ((st.get_scan(scan_id, owner=OWNER) or {}).get("run") or {}).get("scope") or {}
    return scope.get("sp_checkpoint") or {}


def _files_row(st, scan_id) -> int:
    return int(((st.get_scan(scan_id, owner=OWNER) or {}).get("run") or {}).get("files") or 0)


# ── the checkpoint is written as the listing goes ────────────────────────────────────────────

def test_each_completed_site_is_persisted_before_the_next_one_starts(isolated_store, monkeypatch):
    """The whole point. If the rows only landed at the end, an interruption would still cost the
    estate — so this asserts DURABILITY DURING the walk, not just the totals afterwards."""
    st = isolated_store
    seen_counts: list[int] = []

    class _Watch(_Tenant):
        def __call__(self, source, svc=None, **kw):
            outer = kw.get("sp_site_done")

            def done(site_id, files, inv):
                outer(site_id, files, inv)
                seen_counts.append(st.count_inventory("s-live"))
            kw["sp_site_done"] = done
            return super().__call__(source, svc, **kw)

    _wire(monkeypatch, st, _Watch(["S1", "S2", "S3"]))
    _discover("s-live")
    assert seen_counts == [2, 4, 6], (
        f"inventory did not grow site by site during the listing: {seen_counts}")


def test_the_marker_says_the_listing_finished(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st, _Tenant(["S1", "S2"]))
    _discover("s-done")
    cp = _checkpoint(st, "s-done")
    assert cp["listing_complete"] is True
    assert sorted(cp["sites"]) == ["S1", "S2"]


def test_a_scan_killed_mid_listing_leaves_a_marker_that_says_so(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], die_after=2))
    try:
        _discover("s-partial")
    except RuntimeError:
        pass
    cp = _checkpoint(st, "s-partial")
    assert cp["listing_complete"] is False
    assert sorted(cp["sites"]) == ["S1", "S2"]
    assert st.count_inventory("s-partial") == 4


# ── the resume ───────────────────────────────────────────────────────────────────────────────

def test_the_retry_lists_only_what_is_left_and_finishes_the_estate(isolated_store, monkeypatch):
    st = isolated_store
    dying = _Tenant(["S1", "S2", "S3"], die_after=2)
    _wire(monkeypatch, st, dying)
    try:
        _discover("s-resume")
    except RuntimeError:
        pass
    assert dying.walked == ["S1", "S2"]

    resumed = _Tenant(["S1", "S2", "S3"])
    _wire(monkeypatch, st, resumed)
    _discover("s-resume")
    assert resumed.walked == ["S3"], (
        "the retry re-walked sites the first attempt had already persisted")
    files = {r["file"] for r in st.list_inventory("s-resume")}
    assert files == {f"S{s}-{n}.docx" for s in (1, 2, 3) for n in (0, 1)}


def test_the_finished_run_counts_the_WHOLE_estate_not_just_the_tail(isolated_store, monkeypatch):
    """scan_runs.files is what every screen renders as the estate. A resumed run that reported
    only the two sites this attempt listed would show a six-document estate as two."""
    st = isolated_store
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], die_after=2))
    try:
        _discover("s-count")
    except RuntimeError:
        pass
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"]))
    _discover("s-count")
    assert _files_row(st, "s-count") == 6


def test_a_resume_whose_remaining_sites_hold_nothing_still_offers_assess(isolated_store,
                                                                        monkeypatch):
    """The empty-tail case. `items` is what decides finalize-vs-Assess, and on a resume it holds
    only this attempt's share — so a last site with nothing assessable in it would close a run
    whose other twenty-eight sites are full of documents awaiting assessment."""
    st = isolated_store
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], die_after=2))
    try:
        _discover("s-tail")
    except RuntimeError:
        pass
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], per_site=0))
    _discover("s-tail")
    assert st.get_setting("assess_params:s-tail"), (
        "the run finalized instead of offering Assess over the sites already listed")


def test_a_listing_that_finished_is_still_the_old_skip_the_listing_resume(isolated_store,
                                                                          monkeypatch):
    """The pre-existing checkpoint resume (inventory persisted, crash afterwards) must keep
    working exactly as it did — it is the case `count_inventory > 0` was written for, and the
    marker's job is to distinguish it from the partial one, not to replace it."""
    st = isolated_store
    _wire(monkeypatch, st, _Tenant(["S1", "S2"]))
    _discover("s-full")
    again = _Tenant(["S1", "S2"])
    _wire(monkeypatch, st, again)
    _discover("s-full")
    assert again.walked == [], "a completed listing was walked again on retry"


# ── THE GUARD. A resume must not be read as a permissions collapse. ──────────────────────────

def _published_baseline(st, per_site=40):
    """A prior, published, whole-source scan of the same three sites — the shape
    last_published_whole_source_baseline looks for. 120 documents, so a two-site tail of 4 is
    well under the collapse ratio."""
    tenant = _Tenant(["S1", "S2", "S3"], per_site=per_site)
    return tenant


def test_a_resumed_scan_is_not_failed_as_a_scope_collapse(isolated_store, monkeypatch):
    """THE LOAD-BEARING CASE. Without prior_count the guard sees a 120-document estate followed
    by this attempt's 40-document tail, calls it a collapse, and blocks the scan with a
    permissions diagnosis that is simply wrong."""
    st = isolated_store
    _wire(monkeypatch, st, _published_baseline(st))
    _discover("s-base")
    assert st.count_inventory("s-base") == 120

    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], per_site=40, die_after=2))
    try:
        _discover("s-new")
    except RuntimeError:
        pass
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], per_site=40))
    _discover("s-new")

    run = (st.get_scan("s-new", owner=OWNER) or {}).get("run") or {}
    scope = run.get("scope") or {}
    assert "integrity" not in scope, (
        f"a resumed scan was blocked as a scope collapse: {scope.get('integrity')}")
    assert run.get("status") != "failed"
    assert st.count_inventory("s-new") == 120


def test_a_REAL_collapse_on_a_resumed_scan_is_still_caught(isolated_store, monkeypatch):
    """The other direction, and the reason `prior_count` is added rather than the guard being
    skipped on resumes. A resumed run whose remaining sites genuinely lost their contents must
    still be refused — otherwise "resume" becomes a way to smuggle a collapse past the check."""
    st = isolated_store
    _wire(monkeypatch, st, _published_baseline(st))
    _discover("s-base2")

    # Attempt 1 checkpoints one site (20 docs); the retry then finds the remaining two sites
    # empty. 20 of 120 is under the 0.25 ratio, so this IS the collapse the guard is for — and
    # the retry's own listing is EMPTY, which is exactly the shape that used to return early.
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], per_site=20, die_after=1))
    try:
        _discover("s-collapse")
    except RuntimeError:
        pass
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], per_site=0))
    with pytest.raises(RuntimeError, match="scope collapse"):
        _discover("s-collapse")

    run = (st.get_scan("s-collapse", owner=OWNER) or {}).get("run") or {}
    scope = run.get("scope") or {}
    assert (scope.get("integrity") or {}).get("code") == "unexpected_scope_collapse", (
        "a genuine collapse slipped through on a resumed scan")
    # The count the refusal names is the count the row carries — 20 already persisted plus the
    # nothing this attempt found, not the empty listing on its own.
    assert scope["integrity"]["current_count"] == 20
    assert run.get("status") == "failed"


# ── the kill switch ──────────────────────────────────────────────────────────────────────────

def test_ACP_SP_CHECKPOINT_0_restores_the_atomic_listing(isolated_store, monkeypatch):
    """One environment variable back to the previous behaviour, for an operator who needs it.
    No marker, no mid-listing rows, and therefore no resume."""
    st = isolated_store
    monkeypatch.setenv("ACP_SP_CHECKPOINT", "0")
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], die_after=2))
    try:
        _discover("s-off")
    except RuntimeError:
        pass
    assert st.count_inventory("s-off") == 0
    assert _checkpoint(st, "s-off") == {}


def test_a_resumed_runs_per_site_breakdown_reports_the_real_counts(isolated_store, monkeypatch):
    """End to end for the same rule: after the retry, the scope's per-site rows must say what
    each site actually held — including the sites this attempt never walked."""
    st = isolated_store
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"], die_after=2))
    try:
        _discover("s-breakdown")
    except RuntimeError:
        pass
    _wire(monkeypatch, st, _Tenant(["S1", "S2", "S3"]))
    _discover("s-breakdown")
    scope = ((st.get_scan("s-breakdown", owner=OWNER) or {}).get("run") or {}).get("scope") or {}
    rows = {s["id"]: s for s in (scope.get("sites") or [])}
    assert set(rows) == {"S1", "S2", "S3"}
    assert [rows[s]["listed"] for s in ("S1", "S2", "S3")] == [2, 2, 2], (
        f"a resumed site reported a count it did not walk rather than the one it holds: {rows}")
    assert rows["S1"]["resumed"] is True and "resumed" not in rows["S3"]
