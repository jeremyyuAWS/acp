"""Per-site checkpoints and resumable SharePoint scans (Phase 4).

WHAT WAS WRONG. A SharePoint listing was ATOMIC: `_sp_list` walked every selected site and the
handler persisted the whole inventory in one write afterwards. So a thirty-site estate that died
at site twenty-eight — a token refresh, a worker restart, an OOM kill, any of the things that
happen to a run measured in hours — threw away twenty-eight sites' worth of Graph calls and
began again at site one. The bigger the tenant, the longer the run, the likelier the interruption
and the more expensive it was: precisely inverted.

THE SEAM. `_sp_list` now emits each site as it finishes (`site_done_cb`) and accepts the sites a
previous attempt already persisted (`skip_sites`). The scanner owns no store and deliberately
learns nothing about what the caller does with either.

WHAT MUST HOLD, and why each is separate rather than one end-to-end assertion — these fail
independently and a single flow test would not say which:

  1. A finished site is emitted ONCE, with exactly its own share of the listing and nothing from
     the site before or after it.
  2. A site the budget TRUNCATED is never emitted. `skip_sites` is what a resume trusts to not
     walk a site again, so emitting a half-listed site is how the half becomes the whole.
  3. A skipped site is not walked — no Graph call spent on it — and is still ON THE REPORT, as
     complete. A resumed run whose breakdown named only the two sites it happened to finish
     would read as a two-site scan of a thirty-site estate.
  4. A site whose libraries failed is not emitted either, and neither is a blocked one.
  5. A callback that raises does not fail the scan. A checkpoint is an optimisation; a scan that
     dies because its progress note could not be written is worse than one with no notes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_graph(routes: dict, seen: list | None = None):
    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                out = payload() if callable(payload) else payload
                if isinstance(out, int):
                    return _Resp({}, out)
                return _Resp(out)
        raise AssertionError(f"unexpected Graph URL: {url}")
    return get


def _tenant(seen=None, *, per_site=1, media=False):
    """Sites S1 and S2, one library each. `media` adds a non-scannable item per site so the
    inventory split has something to partition too."""
    def _children(drive):
        rows = [{"id": f"{drive}-i{n}", "name": f"{drive}-{n}.docx", "file": {}}
                for n in range(per_site)]
        if media:
            rows.append({"id": f"{drive}-vid", "name": f"{drive}.mp4", "file": {}})
        return {"value": rows}
    return _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives": {"value": [{"id": "d1", "name": "A"}]},
        "https://graph.microsoft.com/v1.0/sites/S2/drives": {"value": [{"id": "d2", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/drives/d1/root/children": _children("d1"),
        "https://graph.microsoft.com/v1.0/drives/d2/root/children": _children("d2"),
    }, seen)


def _recorder():
    calls: list = []

    def cb(site_id, files, inventory):
        calls.append((site_id, [f["name"] for f in files], [r["file"] for r in inventory]))
    return calls, cb


# ── 1. each finished site, exactly once, with only its own share ─────────────────────────────

def test_each_site_is_emitted_once_with_its_own_files(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant())
    calls, cb = _recorder()
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], site_done_cb=cb)
    assert [c[0] for c in calls] == ["S1", "S2"], "one emission per site, in selection order"
    assert [c[1] for c in calls] == [["d1-0.docx"], ["d2-0.docx"]], (
        "a site was handed another site's files — the slice boundaries are wrong")
    assert sorted(f["name"] for f in files) == ["d1-0.docx", "d2-0.docx"]


def test_the_non_scannable_half_is_partitioned_by_site_too(monkeypatch):
    """The inventory is the other half of the same estate. A checkpoint that persisted a site's
    documents but not its media would resume with the media gone from that site for good — the
    site is skipped on the retry, so nothing ever lists it again."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant(media=True))
    calls, cb = _recorder()
    inv: list = []
    scanner._sp_list("tok", 50, sites=["S1", "S2"], inventory_out=inv, site_done_cb=cb)
    assert [c[2] for c in calls] == [["d1.mp4"], ["d2.mp4"]]


def test_an_absent_callback_changes_nothing(monkeypatch):
    """The parameter defaults to None and a caller that has not opted in must not be able to tell
    it exists — the same discipline `sites` and `locations` follow."""
    import httpx
    seen: list = []
    monkeypatch.setattr(httpx, "get", _tenant(seen))
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope)
    assert sorted(f["name"] for f in files) == ["d1-0.docx", "d2-0.docx"]
    assert [s["status"] for s in scope["sites"]] == ["complete", "complete"]


# ── 2. a truncated site is never emitted ─────────────────────────────────────────────────────

def test_the_site_the_budget_cut_off_is_not_checkpointed(monkeypatch):
    """S1 has TWO libraries and the shared budget runs out between them, so S1 itself is only
    half listed and S2 is never reached. Neither may be handed to the caller: `skip_sites` is a
    promise that the site is COMPLETE, and a resume that believed it would publish the fragment
    as the whole site — the one under-report this connector's design is against, arrived at by
    the feature meant to protect the estate."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives":
            {"value": [{"id": "d1a", "name": "A"}, {"id": "d1b", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/sites/S2/drives": {"value": [{"id": "d2", "name": "C"}]},
        "https://graph.microsoft.com/v1.0/drives/d1a/root/children":
            {"value": [{"id": f"a{n}", "name": f"a{n}.docx", "file": {}} for n in range(2)]},
        "https://graph.microsoft.com/v1.0/drives/d1b/root/children":
            {"value": [{"id": f"b{n}", "name": f"b{n}.docx", "file": {}} for n in range(2)]},
        "https://graph.microsoft.com/v1.0/drives/d2/root/children":
            {"value": [{"id": "c0", "name": "c0.docx", "file": {}}]},
    }))
    calls, cb = _recorder()
    scope: dict = {}
    scanner._sp_list("tok", 2, sites=["S1", "S2"], scope_out=scope, site_done_cb=cb)
    statuses = {s["id"]: s["status"] for s in scope["sites"]}
    assert statuses["S1"] == "partial" and statuses["S2"] == "skipped"
    assert calls == [], f"a truncated site was checkpointed: {calls}"


def test_a_site_that_finished_before_the_cap_is_still_checkpointed(monkeypatch):
    """The other half of the same rule, and the reason the cap case is not just "emit nothing on
    truncation": S1 completed honestly, and losing it on the retry is the cost this whole feature
    exists to stop."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant(per_site=2))
    calls, cb = _recorder()
    scope: dict = {}
    scanner._sp_list("tok", 2, sites=["S1", "S2"], scope_out=scope, site_done_cb=cb)
    statuses = {s["id"]: s["status"] for s in scope["sites"]}
    assert statuses["S1"] == "complete" and statuses["S2"] == "skipped"
    assert [c[0] for c in calls] == ["S1"]
    assert c1_names(calls) == ["d1-0.docx", "d1-1.docx"]


def c1_names(calls):
    return calls[0][1]


# ── 3. a skipped site is not walked, and is still on the report ──────────────────────────────

def test_a_skipped_site_costs_no_graph_call(monkeypatch):
    import httpx
    seen: list = []
    monkeypatch.setattr(httpx, "get", _tenant(seen))
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], skip_sites={"S1"})
    assert [f["name"] for f in files] == ["d2-0.docx"]
    assert not [u for u in seen if "/sites/S1" in u or "/drives/d1" in u], (
        "a site the caller had already persisted was walked again")


def test_a_skipped_site_stays_on_the_report_as_complete(monkeypatch):
    """The exit gate is "no site silently omitted". A breakdown that named only the sites this
    ATTEMPT walked would omit twenty-eight of thirty on the run that finishes the estate."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant())
    scope: dict = {}
    scanner._sp_list("tok", 50, sites=["S1", "S2"], skip_sites={"S1"}, scope_out=scope)
    rows = {s["id"]: s for s in scope["sites"]}
    assert set(rows) == {"S1", "S2"}
    assert rows["S1"]["status"] == "complete" and rows["S1"]["resumed"] is True
    assert rows["S2"]["status"] == "complete" and "resumed" not in rows["S2"]


def test_a_resumed_site_is_not_re_emitted(monkeypatch):
    """It is already persisted. Emitting it would re-write rows the caller has, and — worse —
    with the EMPTY file list this attempt holds for it, which a caller that trusted the payload
    rather than the store would read as the site having been emptied."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant())
    calls, cb = _recorder()
    scanner._sp_list("tok", 50, sites=["S1", "S2"], skip_sites={"S1"}, site_done_cb=cb)
    assert [c[0] for c in calls] == ["S2"]


def test_skipping_every_site_lists_nothing_and_reports_all_of_them(monkeypatch):
    """The final attempt of a run that had one site left, which then turned out to be done."""
    import httpx
    seen: list = []
    monkeypatch.setattr(httpx, "get", _tenant(seen))
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], skip_sites={"S1", "S2"},
                             scope_out=scope)
    assert files == [] and seen == []
    assert [s["status"] for s in scope["sites"]] == ["complete", "complete"]


# ── 4. failures are not checkpointed ─────────────────────────────────────────────────────────

def test_a_site_whose_libraries_are_unreadable_is_not_emitted(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives": lambda: 403,
        "https://graph.microsoft.com/v1.0/sites/S2/drives": {"value": [{"id": "d2", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/drives/d2/root/children":
            {"value": [{"id": "d2-i0", "name": "d2-0.docx", "file": {}}]},
    }))
    calls, cb = _recorder()
    scope: dict = {}
    scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope, site_done_cb=cb)
    assert {s["id"]: s["status"] for s in scope["sites"]}["S1"] == "blocked"
    assert [c[0] for c in calls] == ["S2"], "a blocked site was checkpointed as done"


def test_a_site_with_no_visible_libraries_is_emitted_empty(monkeypatch):
    """It completed — there is genuinely nothing there. Re-resolving it on a retry would pay the
    Graph calls again to learn the same nothing, and it never produces a target, so the emission
    boundary in the consumption loop cannot reach it."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives": {"value": []},
        "https://graph.microsoft.com/v1.0/sites/S2/drives": {"value": [{"id": "d2", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/drives/d2/root/children":
            {"value": [{"id": "d2-i0", "name": "d2-0.docx", "file": {}}]},
    }))
    calls, cb = _recorder()
    scanner._sp_list("tok", 50, sites=["S1", "S2"], site_done_cb=cb)
    assert sorted(c[0] for c in calls) == ["S1", "S2"]
    assert dict((c[0], c[1]) for c in calls)["S1"] == []


# ── 5. the checkpoint never fails the scan ───────────────────────────────────────────────────

def test_a_raising_callback_does_not_stop_the_listing(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant())

    def cb(site_id, files, inventory):
        raise RuntimeError("the database is down")

    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], site_done_cb=cb)
    assert sorted(f["name"] for f in files) == ["d1-0.docx", "d2-0.docx"], (
        "a failed checkpoint write cost the scan the estate it had already listed")


# ── what a skipped site is REPORTED as holding ───────────────────────────────────────────────

def test_a_skipped_site_reports_the_counts_the_caller_supplies(monkeypatch):
    """The exit gate is auditable per-site totals. A resumed site reported `complete` beside the
    zero this attempt walked is a WRONG number, not a missing one — a reader cannot tell it from
    a site that genuinely held nothing, which is the one confusion the per-site report exists to
    remove. The caller has the counts (they are in its own inventory), so it hands them back."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant())
    scope: dict = {}
    scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope,
                     skip_sites={"S1": {"listed": 40, "estate": 57, "name": "Finance"}})
    row = {s["id"]: s for s in scope["sites"]}["S1"]
    assert (row["listed"], row["estate"], row["name"]) == (40, 57, "Finance")
    assert row["status"] == "complete" and row["resumed"] is True


def test_the_set_spelling_still_works_and_says_zero(monkeypatch):
    """A caller with nothing to report gets zeros — which is the honest answer to "you told me
    nothing", and is why the dict form exists rather than being inferred."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant())
    scope: dict = {}
    scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope, skip_sites={"S1"})
    row = {s["id"]: s for s in scope["sites"]}["S1"]
    assert (row["listed"], row["estate"]) == (0, 0) and row["resumed"] is True
