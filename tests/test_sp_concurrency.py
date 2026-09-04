"""Walking libraries concurrently — and the property that makes it safe to turn on.

THE TRAP. `_sp_list` spends one shared budget across every selected site, and Phase 1 pins two
things that depend on the ORDER it is spent in: "one budget, not one per site", and "a site the
budget never reached is truncation, recorded as skipped". Consume results as they arrive and
WHICH sites get skipped becomes whichever library happened to return first — the same tenant,
scanned twice, reports a different estate. A count an operator cannot reproduce is worse than a
slow scan, and a lock around the budget removes the race without removing that.

THE RESOLUTION: dispatch concurrently, CONSUME IN SELECTION ORDER. The budget is spent by the
consumer, in the order the operator chose their sites, so the estate is identical at every
concurrency — which is exactly what these tests assert, by running the same fixture at 1 and at
4 and comparing everything an operator would ever read.

AND SERIAL IS THE DEFAULT, which is a refusal rather than caution. Overlapping walks dispatch a
library before the budget that decides whether its result is wanted has been spent, so a scan
with a tight cap walks libraries whose documents are then discarded — real Graph calls against a
customer's tenant, for an estate that is already a floor. Phase 1 rejected that when it chose to
walk libraries lazily; overriding it to gain wall-clock is the operator's trade to make.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload, self.status_code = payload, 200
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _tenant(sites, per_library=2, seen=None, slow=None):
    drives_by_site = dict(sites)

    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        for site, drives in drives_by_site.items():
            if url.startswith(f"https://graph.microsoft.com/v1.0/sites/{site}/drives"):
                return _Resp({"value": [{"id": d, "name": f"lib-{d}"} for d in drives]})
            if url.startswith(f"https://graph.microsoft.com/v1.0/sites/{site}?"):
                return _Resp({"displayName": f"site-{site}"})
        for drives in drives_by_site.values():
            for d in drives:
                if url.startswith(f"https://graph.microsoft.com/v1.0/drives/{d}/root/children"):
                    if slow and d in slow:
                        # Finishing LAST while being selected FIRST is the case that catches a
                        # consumer which takes results as they arrive.
                        import time as _t
                        _t.sleep(slow[d])
                    return _Resp({"value": [
                        {"id": f"{d}-i{n}", "name": f"{d}-{n}.docx", "file": {"mimeType": "x"},
                         "parentReference": {"driveId": d, "path": "/drive/root:"}}
                        for n in range(per_library)]})
        raise AssertionError(f"unexpected Graph URL: {url}")
    return get


def _run(monkeypatch, sites, *, concurrency, max_files=500, per_library=2, slow=None, seen=None):
    import httpx
    monkeypatch.setenv("ACP_SP_CONCURRENCY", str(concurrency))
    monkeypatch.setattr(httpx, "get", _tenant(sites, per_library, seen=seen, slow=slow))
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: f"site-{s}", raising=True)
    scope: dict = {}
    inv: list = []
    files = scanner._sp_list("tok", max_files, sites=[s for s, _ in sites],
                             inventory_out=inv, scope_out=scope)
    return files, inv, scope


def _estate(files, inv, scope):
    """Everything an operator reads. Not just the count — two different estates can share one."""
    return {
        "files": sorted((f["name"], f.get("driveId"), f.get("siteId")) for f in files),
        "inventory": sorted((r["file"], r["drive_id"]) for r in inv),
        # `_sp_list` records truncation on the estate inventory it builds; `_list`'s
        # own top-level `truncated` is derived from it one layer up.
        "truncated": scope["inventory"]["truncated"],
        "sites": [(s["id"], s["status"], s["listed"]) for s in scope["sites"]],
    }


SITES = [(f"S{n}", [f"d{n}"]) for n in range(8)]


# ── the gate ─────────────────────────────────────────────────────────────────────────────────

def test_the_estate_is_identical_serial_and_concurrent(monkeypatch):
    serial = _estate(*_run(monkeypatch, SITES, concurrency=1))
    parallel = _estate(*_run(monkeypatch, SITES, concurrency=4))
    assert parallel == serial


def test_the_estate_is_identical_when_the_FIRST_site_finishes_LAST(monkeypatch):
    """The case a consume-as-they-arrive implementation gets wrong. S0 is selected first and
    returns last; its documents must still come first and its budget must still be spent first."""
    serial = _estate(*_run(monkeypatch, SITES, concurrency=1))
    parallel = _estate(*_run(monkeypatch, SITES, concurrency=4, slow={"d0": 0.05}))
    assert parallel == serial


def test_the_TRUNCATION_BOUNDARY_is_identical_too(monkeypatch):
    """The half that actually depends on ordering. With the budget too small for the estate, WHICH
    sites end up skipped is the thing concurrency could scramble — and the thing an operator would
    never be able to reproduce."""
    serial = _estate(*_run(monkeypatch, SITES, concurrency=1, max_files=5))
    parallel = _estate(*_run(monkeypatch, SITES, concurrency=4, max_files=5, slow={"d0": 0.05}))
    assert serial["truncated"] is True
    assert parallel == serial
    assert [st for _, st, _ in serial["sites"]].count("skipped") > 0, \
        "the fixture did not actually truncate — the assertion above proves nothing"


# ── serial is the default, and it costs nothing it did not before ────────────────────────────

def test_the_default_is_serial(monkeypatch):
    monkeypatch.delenv("ACP_SP_CONCURRENCY", raising=False)
    assert scanner._sp_concurrency() == 1


def test_serial_walks_no_library_the_budget_never_reaches(monkeypatch):
    """Phase 1's own decision, kept. Walking a library whose result is then discarded spends real
    Graph calls against a customer's tenant for an estate that is already a floor."""
    seen: list = []
    _run(monkeypatch, SITES, concurrency=1, max_files=1, seen=seen)
    walked = {u.split("/drives/")[1].split("/")[0] for u in seen if "/root/children" in u}
    assert walked == {"d0"}, f"walked libraries the cap had already ruled out: {walked}"


def test_the_look_ahead_is_bounded_by_the_concurrency(monkeypatch):
    """Not a full dispatch. Submitting every library up front would walk all eight of a truncated
    estate to use the first one — exactly the cost the serial default exists to avoid — so the
    window advances only as the consumer asks."""
    seen: list = []
    _run(monkeypatch, SITES, concurrency=3, max_files=1, seen=seen)
    walked = {u.split("/drives/")[1].split("/")[0] for u in seen if "/root/children" in u}
    assert len(walked) <= 3, f"look-ahead ran past its window: {walked}"


@pytest.mark.parametrize("bad", ["", "nonsense", "-3", "0"])
def test_a_malformed_concurrency_setting_falls_back_to_serial(monkeypatch, bad):
    monkeypatch.setenv("ACP_SP_CONCURRENCY", bad)
    assert scanner._sp_concurrency() == 1


def test_the_concurrency_is_capped(monkeypatch):
    """A wide fan-out is the fastest way to earn a 429 for the whole scan."""
    monkeypatch.setenv("ACP_SP_CONCURRENCY", "500")
    assert scanner._sp_concurrency() == 16


# ── failure isolation survives the pipeline ──────────────────────────────────────────────────

def test_a_library_that_raises_is_still_isolated_to_its_site(monkeypatch):
    """Phase 1's guarantee, through a thread. A future that re-raises on .result() must reach the
    same per-library handler the direct call did, or one broken library takes the estate."""
    import httpx
    monkeypatch.setenv("ACP_SP_CONCURRENCY", "4")
    inner = _tenant(SITES)

    def get(url, headers=None, timeout=None, follow_redirects=None):
        if "/drives/d3/root/children" in url:
            raise RuntimeError("throttled out")
        return inner(url)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: s, raising=True)
    scope: dict = {}
    files = scanner._sp_list("tok", 500, sites=[s for s, _ in SITES], scope_out=scope)
    assert len(files) == 14, "one broken library cost the other seven sites"
    by_id = {s["id"]: s for s in scope["sites"]}
    assert by_id["S3"]["status"] == "partial" and "throttled out" in by_id["S3"]["error"]
    assert by_id["S4"]["status"] == "complete"


def test_a_blocked_site_never_reaches_the_pipeline(monkeypatch):
    """Its libraries were never resolved, so there is nothing to walk — and asking the pipeline
    for a unit it does not have must not be how that is discovered."""
    import httpx
    monkeypatch.setenv("ACP_SP_CONCURRENCY", "4")
    inner = _tenant(SITES)

    def get(url, headers=None, timeout=None, follow_redirects=None):
        if "/sites/S2/drives" in url:
            r = _Resp({"error": {"message": "Access denied"}})
            r.status_code = 403
            return r
        return inner(url)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: s, raising=True)
    scope: dict = {}
    files = scanner._sp_list("tok", 500, sites=[s for s, _ in SITES], scope_out=scope)
    assert len(files) == 14
    by_id = {s["id"]: s for s in scope["sites"]}
    assert by_id["S2"]["status"] == "blocked" and "Sites.Read.All" in by_id["S2"]["error"]


# ── throttling is attributed to the library that actually paid it ────────────────────────────

def test_a_throttled_library_is_named_even_while_others_walk_beside_it(monkeypatch):
    """A snapshot taken around one site's turn in the consumption loop also catches every retry
    the OTHER sites spent in parallel — so the count lands on whichever site happened to be in
    the loop, and an operator chasing a throttled library is sent to the wrong one.

    Attributed per library, from that library's own thread, so the number survives concurrency.
    """
    import httpx
    monkeypatch.setenv("ACP_SP_CONCURRENCY", "4")
    inner = _tenant(SITES)
    state = {"n": 0}

    def get(url, headers=None, timeout=None, follow_redirects=None):
        if "/drives/d5/root/children" in url and state["n"] < 2:
            state["n"] += 1
            r = _Resp({"error": {}})
            r.status_code = 429
            return r
        return inner(url)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: s, raising=True)
    scope: dict = {}
    scanner._sp_list("tok", 500, sites=[s for s, _ in SITES], scope_out=scope)
    by_id = {s["id"]: s for s in scope["sites"]}
    assert by_id["S5"].get("throttled") == 2, "the throttling was not attributed to S5"
    assert all("throttled" not in by_id[f"S{n}"] for n in range(8) if n != 5), \
        "another site was blamed for S5's throttling"


def test_the_global_retry_counter_is_guarded(monkeypatch):
    """`d[k] = d.get(k, 0) + 1` is a read-modify-write, and two walking threads can read the same
    value and both write back the same increment. A diagnostic that undercounts throttling is one
    that tells an operator their tenant is fine."""
    import inspect
    src = inspect.getsource(scanner._sp_note_retry)
    assert "_SP_RETRIES_LOCK" in src
