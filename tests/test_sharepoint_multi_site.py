"""SharePoint estate scans that span SEVERAL sites, not one.

THE DEFECT THIS FILE IS ABOUT. `_sp_locations` returned a single `site` and kept the FIRST bare
root — `elif site is None` — so a scan asked for five sites walked one and returned it as the
answer. No error, no truncation flag, no line in the log: the run completed, the Discover tab
showed a plausible count with a plausible boundary, and every number computed from it (coverage,
the reconciliation, the compliance assertion) was a fraction of the estate the operator asked
about. That is the one failure discovery cannot ship, for the same reason `search(q='')` was
replaced by a `/children` walk: a partial listing is indistinguishable from a small estate.

What the multi-site path has to get right, and what each case below pins:

  * every selected site is walked, and its items keep the drive they came from;
  * ONE budget is shared across all of them, so N sites do not cost N x max_files against a
    customer's tenant;
  * a site left unwalked — by the budget or by the site cap — is TRUNCATION, reported as such;
  * the recorded scope names the sites, so a count is never rendered without its boundary;
  * a single-site or OneDrive run is bit-for-bit what it always was.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.content = b"file-bytes"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_graph(routes: dict, seen: list | None = None):
    """Keyed by URL prefix, recording every URL — WHICH drive was asked is the assertion, since
    the response shape is identical whichever site the items came from."""
    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                return _Resp(payload() if callable(payload) else payload)
        raise AssertionError(f"unexpected Graph URL: {url}")
    return get


def _two_site_tenant(files_per_site: int = 1, seen: list | None = None):
    """Sites S1 and S2, one library each, `files_per_site` documents in each."""
    def _children(drive):
        return {"value": [{"id": f"{drive}-i{n}", "name": f"{drive}-{n}.docx", "file": {}}
                          for n in range(files_per_site)]}
    return _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives": {"value": [{"id": "d1", "name": "A"}]},
        "https://graph.microsoft.com/v1.0/sites/S2/drives": {"value": [{"id": "d2", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/drives/d1/root/children": _children("d1"),
        "https://graph.microsoft.com/v1.0/drives/d2/root/children": _children("d2"),
    }, seen)


# ── the listing ──────────────────────────────────────────────────────────────────────────────

def test_every_selected_site_is_walked(monkeypatch):
    """One site's documents returned as the estate is the whole defect. Both sites, or nothing."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"])
    assert sorted(f["name"] for f in files) == ["d1-0.docx", "d2-0.docx"]


def test_items_keep_the_drive_they_came_from_across_sites(monkeypatch):
    """A Graph item id is unique only WITHIN a drive, so an item listed from site 2 and
    downloaded against site 1's drive does not reliably fail — it can return a different
    document with the same id. Stamping the drive per item is what makes the download honest."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"])
    assert {f["name"]: f["driveId"] for f in files} == {"d1-0.docx": "d1", "d2-0.docx": "d2"}


def test_the_same_site_twice_is_walked_once(monkeypatch):
    """Duplicate selection is the same estate, not twice the estate — and a re-walk spends
    budget belonging to a site that has not been reached yet."""
    seen: list[str] = []
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant(seen=seen))
    files = scanner._sp_list("tok", 50, sites=["S1", "S1"])
    assert len(files) == 1
    assert sum(1 for u in seen if u.startswith(
        "https://graph.microsoft.com/v1.0/drives/d1/root/children")) == 1


def test_site_singular_is_folded_into_the_list(monkeypatch):
    """One loop, not two modes: a single site is a list of one, and the old spelling still
    reaches it."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    assert [f["name"] for f in scanner._sp_list("tok", 50, site="S2")] == ["d2-0.docx"]


def test_onedrive_is_untouched_by_the_plural_parameter(monkeypatch):
    """No site and no sites → /me/drive and NO driveId, exactly the pre-multi-site shape the
    download path depends on."""
    seen: list[str] = []
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/me/drive/root/children": {"value": [
            {"id": "i1", "name": "mine.docx", "file": {}}]},
    }, seen))
    [rec] = scanner._sp_list("tok", 50, sites=[])
    assert rec["name"] == "mine.docx" and "driveId" not in rec
    assert all("me/drive" in u for u in seen)


# ── the budget, and what it means when it runs out ───────────────────────────────────────────

def test_the_budget_is_shared_across_sites_not_multiplied(monkeypatch):
    """max_files bounds the WORK a scan may do. Per-site budgets would multiply that by the
    number of sites selected, so a 30-site run would quietly cost 30x its cap against a
    customer's tenant."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant(files_per_site=5))
    files = scanner._sp_list("tok", 6, sites=["S1", "S2"])
    assert len(files) == 6


def test_a_site_the_budget_never_reached_is_truncation(monkeypatch):
    """The estate is a FLOOR, and has to say so. Returning site 1 as though it were the whole
    selection is the same failure as returning library A as though it were the site."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant(files_per_site=5))
    scope: dict = {}
    scanner._sp_list("tok", 5, sites=["S1", "S2"], scope_out=scope)
    assert scope["inventory"]["truncated"] is True


def test_a_fully_listed_multi_site_estate_is_not_truncated(monkeypatch):
    """The other direction, and the one a cap-shaped check gets wrong: a listing that covered
    every site completely is not truncated however close to the cap it landed."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant(files_per_site=1))
    scope: dict = {}
    scanner._sp_list("tok", 2, sites=["S1", "S2"], scope_out=scope)
    assert scope["inventory"]["truncated"] is False


def test_a_site_with_no_visible_library_does_not_stop_the_others(monkeypatch):
    """A site that scans to zero is a fact about that site. Aborting the run on it would lose
    every other site's documents to one misconfigured team site."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives": {"value": []},
        "https://graph.microsoft.com/v1.0/sites/S2/drives": {"value": [{"id": "d2", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/drives/d2/root/children": {"value": [
            {"id": "i2", "name": "b.docx", "file": {}}]},
    }))
    assert [f["name"] for f in scanner._sp_list("tok", 50, sites=["S1", "S2"])] == ["b.docx"]


# ── one site's failure is not the scan's ─────────────────────────────────────────────────────

def test_a_blocked_site_does_not_discard_the_sites_already_walked(monkeypatch):
    """A tenant of thirty sites reliably contains one the token has lost access to. Letting it
    raise throws away every site already walked and returns nothing — an hour of Graph calls
    against a customer's tenant, discarded by one permission change."""
    import httpx

    def graph(url, headers=None, timeout=None, follow_redirects=None):
        if url.startswith("https://graph.microsoft.com/v1.0/sites/S1/drives"):
            return _Resp({"error": {"message": "Access denied"}}, status=403)
        return _two_site_tenant()(url)

    monkeypatch.setattr(httpx, "get", graph)
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope)
    assert [f["name"] for f in files] == ["d2-0.docx"], "one site's 403 lost the other site"
    by_id = {s["id"]: s for s in scope["sites"]}
    assert by_id["S1"]["status"] == "blocked"
    assert by_id["S2"]["status"] == "complete" and by_id["S2"]["listed"] == 1


def test_a_blocked_site_names_the_permission_and_marks_the_estate_a_floor(monkeypatch):
    """"Sites.Read.All" and "429" are different problems with different owners, so the message is
    kept verbatim. And a run that could not read one of its sites has not measured the estate —
    reporting it complete is the silent-omission failure with an extra step."""
    import httpx

    def graph(url, headers=None, timeout=None, follow_redirects=None):
        if url.startswith("https://graph.microsoft.com/v1.0/sites/S1/drives"):
            return _Resp({"error": {"message": "Access denied"}}, status=403)
        return _two_site_tenant()(url)

    monkeypatch.setattr(httpx, "get", graph)
    scope: dict = {}
    scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope)
    blocked = next(s for s in scope["sites"] if s["id"] == "S1")
    assert "Sites.Read.All" in blocked["error"]
    assert scope["inventory"]["truncated"] is True


def test_a_transport_failure_on_one_site_is_isolated_too(monkeypatch):
    """Not only permissions: a mid-migration site, a throttled one, a Graph 500. The scan carries
    on and says which site it was."""
    import httpx

    def graph(url, headers=None, timeout=None, follow_redirects=None):
        if url.startswith("https://graph.microsoft.com/v1.0/sites/S1/drives"):
            raise RuntimeError("connection reset")
        return _two_site_tenant()(url)

    monkeypatch.setattr(httpx, "get", graph)
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope)
    assert len(files) == 1
    blocked = next(s for s in scope["sites"] if s["id"] == "S1")
    assert blocked["status"] == "blocked" and "connection reset" in blocked["error"]


def test_a_failing_library_does_not_lose_the_rest_of_its_site(monkeypatch):
    """The same isolation one level down. A site with four libraries and one broken one is a
    partial site, not a blocked one — and the distinction is what an operator triages by."""
    import httpx

    def graph(url, headers=None, timeout=None, follow_redirects=None):
        if url.startswith("https://graph.microsoft.com/v1.0/drives/dA/root/children"):
            raise RuntimeError("throttled")
        for prefix, payload in {
            "https://graph.microsoft.com/v1.0/sites/S1/drives": {"value": [
                {"id": "dA", "name": "Broken"}, {"id": "dB", "name": "Fine"}]},
            "https://graph.microsoft.com/v1.0/drives/dB/root/children": {"value": [
                {"id": "i1", "name": "ok.docx", "file": {}}]},
        }.items():
            if url.startswith(prefix):
                return _Resp(payload)
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "get", graph)
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1"], scope_out=scope)
    assert [f["name"] for f in files] == ["ok.docx"]
    [rep] = scope["sites"]
    assert rep["status"] == "partial" and "Broken" in rep["error"]
    assert scope["inventory"]["truncated"] is True


# ── per-site progress ────────────────────────────────────────────────────────────────────────

def test_progress_is_reported_per_site_as_each_one_resolves(monkeypatch):
    """A thirty-site walk is otherwise one silent bar. "Which site is it on, and did any fail?"
    is the question an operator watching a long estate scan actually has."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    ticks: list[list[dict]] = []
    scanner._sp_list("tok", 50, sites=["S1", "S2"],
                     progress_cb=lambda n, sites=None: ticks.append(sites))
    assert len(ticks) >= 2, "no per-site tick — the operator sees one silent bar"
    final = {s["id"]: s["status"] for s in ticks[-1]}
    assert final == {"S1": "complete", "S2": "complete"}


def test_an_older_progress_callback_without_sites_still_works(monkeypatch):
    """A progress diagnostic must never be the thing that fails a scan."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    counts: list[int] = []
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"],
                             progress_cb=lambda n: counts.append(n))
    assert len(files) == 2 and counts


# ── per-document identity ────────────────────────────────────────────────────────────────────

def test_every_document_carries_the_site_and_library_it_came_from(monkeypatch):
    """A Graph driveItem names its drive and nothing else. Once a run spans a SET of sites the
    scan's scope can no longer answer "which site is this document in" — so the walk stamps it,
    and every later phase (per-site metadata, per-library deltas, exception reports, write-back
    targeting) has the boundary it depends on."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"])
    assert {f["name"]: (f["siteId"], f["libraryName"], f["driveId"]) for f in files} == {
        "d1-0.docx": ("S1", "A", "d1"), "d2-0.docx": ("S2", "B", "d2")}


def test_non_scannable_items_carry_it_too(monkeypatch):
    """The inventory row is the estate record. A media file with no site is a hole in exactly the
    report the per-site totals are supposed to be checkable against."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S1/drives": {"value": [{"id": "d1", "name": "A"}]},
        "https://graph.microsoft.com/v1.0/drives/d1/root/children": {"value": [
            {"id": "i1", "name": "clip.mp4", "file": {"mimeType": "video/mp4"},
             "parentReference": {"driveId": "d1"}}]},
    }))
    inv: list[dict] = []
    scanner._sp_list("tok", 50, sites=["S1"], inventory_out=inv)
    assert [(r["site_id"], r["library_name"]) for r in inv] == [("S1", "A")]


def test_a_onedrive_document_has_no_site_to_carry(monkeypatch):
    """Absent, not invented. OneDrive has no site, and a placeholder there would be a boundary
    nobody chose."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/me/drive/root/children": {"value": [
            {"id": "i1", "name": "mine.docx", "file": {}}]},
    }))
    [rec] = scanner._sp_list("tok", 50)
    assert "siteId" not in rec and "libraryName" not in rec


def test_folders_beat_sites_but_the_dropped_sites_are_said_out_loud(monkeypatch):
    """A request carrying both is narrowed to the folders — the tighter boundary and the later
    answer, which is what the label does too. The pre-multi-site code took the same branch and
    never mentioned the site at all; saying so is the difference between a narrowing the operator
    chose and one nobody could see."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/drives/dX/items/F/children": {"value": [
            {"id": "i1", "name": "in-folder.docx", "file": {}}]},
    }))
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1"], locations=[("dX", "F")], scope_out=scope)
    assert [f["name"] for f in files] == ["in-folder.docx"]
    [rep] = scope["sites"]
    assert rep["status"] == "skipped" and "narrowed to the selected folders" in rep["error"]
    assert scope["inventory"]["truncated"] is True


# ── the site cap ─────────────────────────────────────────────────────────────────────────────

def test_sites_past_the_cap_are_dropped_and_the_listing_says_so(monkeypatch):
    """Not silently folded in — that is the single-site defect one level up. The cap bounds the
    work; the truncation flag is what keeps the answer honest about being bounded."""
    monkeypatch.setenv("ACP_SP_MAX_SITES", "1")
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    scope: dict = {}
    files = scanner._sp_list("tok", 50, sites=["S1", "S2"], scope_out=scope)
    assert [f["name"] for f in files] == ["d1-0.docx"]
    assert scope["inventory"]["truncated"] is True


def test_the_cap_is_read_at_call_time_and_defaults_to_thirty(monkeypatch):
    monkeypatch.delenv("ACP_SP_MAX_SITES", raising=False)
    assert scanner._sp_max_sites() == 30
    monkeypatch.setenv("ACP_SP_MAX_SITES", "7")
    assert scanner._sp_max_sites() == 7


@pytest.mark.parametrize("bad", ["", "nonsense", "0", "-3"])
def test_a_malformed_cap_falls_back_rather_than_disabling_the_bound(monkeypatch, bad):
    """A typo in a deployment env var must not turn the cap off — an unbounded selection is a
    scan that does not finish."""
    monkeypatch.setenv("ACP_SP_MAX_SITES", bad)
    assert scanner._sp_max_sites() == 30


def test_the_exit_gate_thirty_sites_one_broken_nothing_silently_omitted(monkeypatch):
    """THE PHASE 1 EXIT GATE, stated as a test.

    A run across 30 representative sites completes without silently omitting a site, and produces
    auditable per-site totals. "Silently" is the load-bearing word: site 7 being unreadable is a
    fact about the tenant, and a perfectly acceptable outcome — what is not acceptable is a run
    that returns 29 sites' documents as the estate with nothing anywhere saying the thirtieth was
    never read. Every site appears in the breakdown, with a status and a count, and the estate is
    marked a floor.
    """
    monkeypatch.delenv("ACP_SP_MAX_SITES", raising=False)
    routes = {}
    for n in range(30):
        routes[f"https://graph.microsoft.com/v1.0/sites/S{n}/drives"] = {
            "value": [{"id": f"d{n}", "name": "Documents"}]}
        routes[f"https://graph.microsoft.com/v1.0/drives/d{n}/root/children"] = {
            "value": [{"id": f"i{n}", "name": f"f{n}.docx", "file": {}}]}
    inner = _fake_graph(routes)

    def graph(url, headers=None, timeout=None, follow_redirects=None):
        if url.startswith("https://graph.microsoft.com/v1.0/sites/S7/drives"):
            return _Resp({"error": {"message": "Access denied"}}, status=403)
        return inner(url)

    import httpx
    monkeypatch.setattr(httpx, "get", graph)
    scope: dict = {}
    files = scanner._sp_list("tok", 500, sites=[f"S{n}" for n in range(30)], scope_out=scope)

    assert len(files) == 29, "a broken site cost the other 29 their documents"
    rows = {r["id"]: r for r in scope["sites"]}
    assert len(rows) == 30, "a selected site is missing from the breakdown entirely"
    assert rows["S7"]["status"] == "blocked" and rows["S7"]["listed"] == 0
    assert all(rows[f"S{n}"]["status"] == "complete" for n in range(30) if n != 7)
    assert sum(r["listed"] for r in rows.values()) == len(files)
    assert scope["inventory"]["truncated"] is True, \
        "29 of 30 sites read, reported as a complete estate"


def test_thirty_sites_are_walked_at_the_default_cap(monkeypatch):
    """The intended production workload: an estate spanning 30 locations in ONE run."""
    monkeypatch.delenv("ACP_SP_MAX_SITES", raising=False)
    routes = {}
    for n in range(30):
        routes[f"https://graph.microsoft.com/v1.0/sites/S{n}/drives"] = {
            "value": [{"id": f"d{n}", "name": "Documents"}]}
        routes[f"https://graph.microsoft.com/v1.0/drives/d{n}/root/children"] = {
            "value": [{"id": f"i{n}", "name": f"f{n}.docx", "file": {}}]}
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph(routes))
    scope: dict = {}
    files = scanner._sp_list("tok", 500, sites=[f"S{n}" for n in range(30)], scope_out=scope)
    assert len(files) == 30
    assert {f["driveId"] for f in files} == {f"d{n}" for n in range(30)}
    assert scope["inventory"]["truncated"] is False


# ── the recorded scope: a count without its boundary is not a fact ───────────────────────────

def _list_sharepoint(monkeypatch, roots, max_files=50):
    scope: dict = {}
    scanner._list("sharepoint", sp_token="tok", folders=roots, max_files=max_files,
                  scope_out=scope)
    return scope


def test_a_multi_site_scan_records_every_site_it_covered(monkeypatch):
    """A two-site run has no singular `site`, so without `sites` the count renders with no
    boundary at all and reads as the whole tenant — the 2026-07-30 defect, one level up."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: {"S1": "Policies",
                                                                "S2": "Finance"}[s])
    scope = _list_sharepoint(monkeypatch, ["S1", "S2"])
    assert scope["kind"] == "sharepoint"
    assert [(s["id"], s["name"]) for s in scope["sites"]] == [("S1", "Policies"), ("S2", "Finance")]
    assert scope["site"] is None, "a multi-site run must not claim to be one of its sites"
    assert scope["kept"] == 2


def test_the_scope_carries_auditable_per_site_totals(monkeypatch):
    """THE EXIT GATE for a multi-site run: no site silently omitted. A grand total cannot show
    that — a site that held nothing and a site that was never opened contribute the same zero to
    it — so each site carries its own libraries, counts and status."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant(files_per_site=2))
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: {"S1": "Policies",
                                                                "S2": "Finance"}[s])
    scope = _list_sharepoint(monkeypatch, ["S1", "S2"])
    assert [(s["id"], s["listed"], s["status"]) for s in scope["sites"]] == [
        ("S1", 2, "complete"), ("S2", 2, "complete")]
    assert scope["sites"][0]["libraries"] == [{"id": "d1", "name": "A"}]
    assert scope["sites"][1]["libraries"] == [{"id": "d2", "name": "B"}]
    assert sum(s["listed"] for s in scope["sites"]) == scope["kept"], \
        "the per-site totals must add up to the run's own count"


def test_a_single_site_scan_still_records_the_singular_fields(monkeypatch):
    """Every existing consumer — the scope chip, the incremental baseline match — reads `site`
    and `site_name`, and a one-site scan is unchanged by the plural form existing."""
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: "Policies")
    scope = _list_sharepoint(monkeypatch, ["S1"])
    assert scope["site"] == "S1" and scope["site_name"] == "Policies"
    # …and the plural field is written too, so a consumer can read one field either way.
    assert [(s["id"], s["name"]) for s in scope["sites"]] == [("S1", "Policies")]


def test_sites_refused_by_the_cap_are_counted_on_the_scope(monkeypatch):
    """`truncated` says the estate is a floor; `sites_omitted` says why, which is the difference
    between "we hit a cap" and "run these as a second scan"."""
    monkeypatch.setenv("ACP_SP_MAX_SITES", "1")
    import httpx
    monkeypatch.setattr(httpx, "get", _two_site_tenant())
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: s)
    scope = _list_sharepoint(monkeypatch, ["S1", "S2"])
    by_id = {s["id"]: s for s in scope["sites"]}
    assert by_id["S1"]["status"] == "complete" and by_id["S1"]["listed"] == 1
    # NAMED AND MARKED SKIPPED, not dropped before anything could record it. A site refused by the
    # cap and absent from the breakdown is precisely the silent omission the exit gate is about.
    assert by_id["S2"]["status"] == "skipped" and by_id["S2"]["listed"] == 0
    assert "site limit" in by_id["S2"]["error"]
    assert scope["sites_omitted"] == 1
    assert scope["truncated"] is True


def test_a_onedrive_scan_records_no_sites_key(monkeypatch):
    """Absent, not empty: `sites: []` on a OneDrive run would read as "a site scan that found no
    sites" to anything checking for the key."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/me/drive/root/children": {"value": [
            {"id": "i1", "name": "mine.docx", "file": {}}]},
    }))
    scope = _list_sharepoint(monkeypatch, [])
    assert "sites" not in scope and scope["site"] is None


def test_delta_reconstruction_is_still_refused_for_a_multi_site_request():
    """sp_delta_since is scoped to exactly ONE Graph drive, so no multi-site request is ever
    "the whole of exactly one drive". A delta that silently answered for one site's drive would
    report that site's changes as the estate's."""
    assert scanner._sp_whole_library_target(None, ["S1", "S2"]) == (False, None)
    assert scanner._sp_whole_library_target(None, ["S1"]) == (False, None)
    assert scanner._sp_whole_library_target(None, ["d1/root"]) == (True, "d1")


# ── the request guard ────────────────────────────────────────────────────────────────────────

def test_a_request_within_the_cap_is_accepted():
    from routes.scans import sharepoint_site_overflow
    assert sharepoint_site_overflow(None, [f"S{n}" for n in range(30)]) is None
    assert sharepoint_site_overflow("S1", None) is None
    assert sharepoint_site_overflow(None, None) is None


def test_a_request_over_the_cap_is_refused_with_the_number_and_the_way_out(monkeypatch):
    """Refused before the scan starts, not truncated after an hour against a customer's tenant.
    The message carries both counts and the env var, because "too many" alone leaves the
    operator guessing how many to remove."""
    monkeypatch.setenv("ACP_SP_MAX_SITES", "2")
    from routes.scans import sharepoint_site_overflow
    msg = sharepoint_site_overflow(None, ["S1", "S2", "S3"])
    assert msg and "3 SharePoint sites" in msg and "at most 2" in msg
    assert "ACP_SP_MAX_SITES" in msg


def test_folders_and_the_no_narrowing_sentinel_are_not_sites(monkeypatch):
    """`<driveId>/<itemId>` is a folder and "root" is Drive's no-narrowing sentinel. Counting
    either as a site would refuse a request the scanner handles correctly."""
    monkeypatch.setenv("ACP_SP_MAX_SITES", "1")
    from routes.scans import sharepoint_site_overflow
    assert sharepoint_site_overflow(None, ["d1/i1", "d1/i2", "d2/i3", "root"]) is None


def test_the_same_site_twice_is_one_site_for_the_guard_too(monkeypatch):
    """The listing collapses the duplicate (see _sp_locations), so the guard must not reject
    what the scanner would have handled."""
    monkeypatch.setenv("ACP_SP_MAX_SITES", "1")
    from routes.scans import sharepoint_site_overflow
    assert sharepoint_site_overflow(None, ["S1", "S1"]) is None


# ── the wiring: the walk's per-site ticks have to reach the job stream ────────────────────────

def test_list_passes_the_progress_callback_through_to_the_walk(monkeypatch):
    """A callback the caller supplies and _list never forwards is a live progress feature that
    exists in the scanner and reaches nobody — the shape that survives review because both halves
    look finished."""
    seen = {}

    def fake_sp_list(token, max_files, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(scanner, "_sp_list", fake_sp_list, raising=True)
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: s, raising=True)
    cb = lambda *a, **k: None       # noqa: E731
    scanner._list("sharepoint", sp_token="tok", folders=["S1", "S2"], scope_out={},
                  progress_cb=cb)
    assert seen.get("progress_cb") is cb
    assert seen.get("sites") == ["S1", "S2"]


def test_a_caller_with_no_callback_calls_the_walk_exactly_as_before(monkeypatch):
    """A caller that has not opted into a feature must not be able to tell it exists — the same
    discipline `locations` and `sites` follow, and the reason four existing stubs still pass."""
    seen = {}

    def fake_sp_list(token, max_files, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(scanner, "_sp_list", fake_sp_list, raising=True)
    scanner._list("sharepoint", sp_token="tok", scope_out={})
    assert "progress_cb" not in seen and "sites" not in seen


def test_the_job_progress_callback_accepts_the_per_site_breakdown():
    """handlers._listing_progress is the other end of the tick. Its signature is what decides
    whether the breakdown reaches the SSE stream or is swallowed as a TypeError the scanner then
    falls back from — silently, into the count-only path."""
    import inspect

    import handlers
    src = inspect.getsource(handlers)
    assert "sites: list | None = None) -> None:" in src, \
        "_listing_progress cannot receive the per-site breakdown"
    assert 'patch["sites"] = sites' in src, "the breakdown never reaches the job state"
