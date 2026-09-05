"""A thirty-site estate, and what it COSTS (Phase 6 — the half that does not need a tenant).

Every other SharePoint test here asks whether the answer is right. This one asks what the answer
cost, because the two failures that only appear at estate scale are invisible in a fixture of two
documents and fatal in a tenant of fifty thousand:

  * **A per-document Graph call.** One round trip per file is free at 2 files, is 50,000 serial
    round trips at FANOUT_MAX_FILES, and is 50,000 more chances to be throttled by a tenant that
    already throttles. Nothing in a correctness test notices it: the estate is identical either
    way.
  * **A per-site multiplication of the budget.** One shared cap is a Phase 1 promise; thirty
    copies of it is thirty times the load against a customer, and again the estate looks fine.

WHAT THIS FILE FOUND. The walk is O(folders) — 90 Graph calls for a 30-site estate whether it
holds 150 documents or 1,500. `_sp_enrich_content_types` was O(DOCUMENTS): 150 calls and 1,500
calls respectively, appended to that walk, unbounded. Its three-strike circuit breaker does not
bound it, because the breaker counts consecutive FAILURES and the expensive case is the one where
every call SUCCEEDS — a tenant that refuses the inline `$expand` on a collection while answering
`/items/{id}/listItem` on a single resource. That tenant is the ordinary large tenant, and it is
exactly the one whose estate is big enough for the cost to matter.

The measurement is the test. `test_the_walk_costs_the_same_whether_the_estate_is_small_or_large`
is what makes the claim checkable rather than asserted, and it is the one to read first.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402

SITES = [f"S{n}" for n in range(30)]


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Tenant:
    """Thirty sites, `libs` libraries each, `docs` documents in each library.

    `expansion` says whether this tenant answers the inline listItem expansion — the single most
    consequential thing about a tenant for the cost of a scan, and the reason both settings are
    exercised. Counts every request by kind, which is the whole point of the fixture.
    """

    def __init__(self, *, docs=5, libs=1, expansion=True, media=0):
        self.docs, self.libs, self.expansion, self.media = docs, libs, expansion, media
        self.calls: dict[str, int] = {}
        self.urls: list[str] = []

    def _count(self, kind):
        self.calls[kind] = self.calls.get(kind, 0) + 1

    def __call__(self, url, headers=None, timeout=None, follow_redirects=None):
        self.urls.append(url)
        if "/listItem" in url:
            self._count("per_item")
            return _Resp({"fields": {"ContentType": "Document"}})
        if "/drives?" in url or ("/sites/" in url and url.rstrip("/").endswith("/drives")):
            self._count("drives")
            site = url.split("/sites/")[1].split("/")[0]
            return _Resp({"value": [{"id": f"{site}-L{i}", "name": f"Lib{i}"}
                                    for i in range(self.libs)]})
        if "/children" in url:
            self._count("children")
            if not self.expansion and ("expand=listItem" in url or "retentionLabel" in url):
                return _Resp({}, 400)
            drive = url.split("/drives/")[1].split("/")[0]
            # A tenant that ANSWERS the expansion returns the listItem inline — which is the
            # whole cost argument for Phase 2 and the reason the fallback is a fallback. A
            # fixture that set `expansion=True` but returned bare items would exercise the
            # expensive path while claiming to test the cheap one.
            inline = ({"listItem": {"contentType": {"name": "Policy"}, "fields": {}}}
                      if self.expansion else {})
            rows = [{"id": f"{drive}-i{n}", "name": f"{drive}-{n}.docx", "file": {}, **inline}
                    for n in range(self.docs)]
            rows += [{"id": f"{drive}-m{n}", "name": f"{drive}-{n}.mp4", "file": {}, **inline}
                     for n in range(self.media)]
            return _Resp({"value": rows})
        self._count("site_name")
        return _Resp({"displayName": "A Site"})


def _scan(monkeypatch, tenant, *, max_files=50000, sites=SITES, inventory=None):
    import httpx
    monkeypatch.setattr(httpx, "get", tenant)
    scope: dict = {}
    files = scanner._sp_list("tok", max_files, sites=sites, scope_out=scope,
                             inventory_out=inventory)
    return files, scope


# ── the cost of the walk itself ──────────────────────────────────────────────────────────────

def test_the_walk_costs_the_same_whether_the_estate_is_small_or_large(monkeypatch):
    """THE LOAD-BEARING MEASUREMENT. A listing request returns a page of documents, so the number
    of them must not depend on how many documents are in the page. A per-document call hidden
    anywhere in the walk is invisible in every other test in this repo and is the difference
    between a scan and an outage on a real estate."""
    small = _Tenant(docs=5)
    big = _Tenant(docs=500)
    _scan(monkeypatch, small)
    _scan(monkeypatch, big)
    assert small.calls["children"] == big.calls["children"], (
        f"the walk's request count moved with the document count — "
        f"{small.calls} vs {big.calls}")
    assert big.calls.get("per_item", 0) == 0, (
        "a tenant that answers the expansion paid a per-document call anyway")


def test_the_walk_costs_one_request_per_library(monkeypatch):
    """And scales with LIBRARIES, which is the dimension it is allowed to scale with: a library is
    a separate drive and there is no way to page two of them in one request."""
    one = _Tenant(libs=1)
    four = _Tenant(libs=4)
    _scan(monkeypatch, one)
    _scan(monkeypatch, four)
    assert one.calls["children"] == 30 and four.calls["children"] == 120


def test_the_site_name_is_read_once_per_site_not_once_per_document(monkeypatch):
    """`site_name` is recorded on every document (Phase 2). Resolving it per document would be
    one Graph call per file for a value that is constant across the site — the exact shape of
    mistake this file exists to catch, and one the metadata work could plausibly have made."""
    t = _Tenant(docs=200)
    files, _ = _scan(monkeypatch, t)
    assert len(files) == 30 * 200
    assert t.calls.get("site_name", 0) <= 30, (
        f"{t.calls.get('site_name')} site-name lookups for 30 sites")
    assert all(f["siteName"] == "A Site" for f in files)


# ── the finding: the content-type fallback was O(documents) ──────────────────────────────────

def test_a_tenant_that_refuses_the_expansion_pays_a_BOUNDED_number_of_calls(monkeypatch):
    """THE BUG THIS FILE FOUND. The three-strike circuit breaker counts consecutive FAILURES, and
    the expensive case is the one where every call succeeds: a tenant that refuses the inline
    `$expand` on a collection but answers `/items/{id}/listItem` on a single resource. Before the
    budget, a 1,500-document estate cost 1,500 extra serial round trips and a 50,000-document one
    cost 50,000."""
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "100")
    t = _Tenant(docs=50, expansion=False)          # 1,500 documents
    files, scope = _scan(monkeypatch, t)
    assert len(files) == 1500
    assert t.calls["per_item"] == 100, (
        f"the per-document fallback was unbounded: {t.calls['per_item']} calls for 1500 documents")
    assert scope["content_type_fallback"]["capped"] is True
    assert scope["content_type_fallback"]["skipped"] == 1400


def test_the_bound_is_on_CALLS_not_on_documents_examined(monkeypatch):
    """A document the walk already read the content type for costs nothing, so it must not spend
    the budget. Counting skips against it would make the cap bite on a tenant that answers the
    expansion and pays nothing at all — a limit applied to the case it was not written for."""
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "10")
    t = _Tenant(docs=100, expansion=True)          # 3,000 documents, all already enriched
    files, scope = _scan(monkeypatch, t)
    assert len(files) == 3000
    assert t.calls.get("per_item", 0) == 0
    assert "content_type_fallback" not in scope, (
        "a tenant that cost nothing was reported as having used the fallback")


def test_a_small_estate_is_enriched_completely(monkeypatch):
    """The fallback was designed for the single-library case and is genuinely useful there. The
    budget must not quietly turn that into a sample — the default is well above it."""
    t = _Tenant(docs=5, expansion=False, libs=1)   # 150 documents, default budget 1000
    files, scope = _scan(monkeypatch, t)
    assert t.calls["per_item"] == 150
    assert all(f.get("content_type") == "Document" for f in files)
    assert scope["content_type_fallback"]["capped"] is False


def test_the_budget_is_read_at_call_time(monkeypatch):
    assert scanner._sp_content_type_budget() == 1000
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "7")
    assert scanner._sp_content_type_budget() == 7


def test_a_nonsense_budget_disables_the_fallback_rather_than_crashing_the_scan(monkeypatch):
    """It is an optimisation. A scan that dies on a malformed knob has traded a missing field for
    a missing estate."""
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "not-a-number")
    assert scanner._sp_content_type_budget() == 1000
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "-5")
    assert scanner._sp_content_type_budget() == 0


def test_the_cap_is_reported_rather_than_absorbed(monkeypatch):
    """An operator seeing content types on 1,000 of 12,000 documents must be able to tell "not
    asked" from "not configured" — and must be told the remedy is the tenant's refusal of the
    inline expansion, not a bigger budget."""
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "5")
    t = _Tenant(docs=10, expansion=False)
    _, scope = _scan(monkeypatch, t)
    cf = scope["content_type_fallback"]
    assert cf["attempted"] == 5 and cf["enriched"] == 5 and cf["capped"] is True
    assert cf["skipped"] == 300 - 5


def test_the_three_strike_breaker_still_stops_a_tenant_that_cannot_answer_at_all(monkeypatch):
    """Unchanged, and asserted because the budget was added to the same loop. A tenant where every
    per-item call fails must stop after three, not after a thousand."""
    monkeypatch.setenv("ACP_SP_CONTENT_TYPE_MAX", "1000")
    t = _Tenant(docs=50, expansion=False)
    real = t.__call__

    def refuse_listitem(url, **kw):
        if "/listItem" in url:
            t.calls["per_item"] = t.calls.get("per_item", 0) + 1
            return _Resp({}, 500)
        return real(url, **kw)
    import httpx
    monkeypatch.setattr(httpx, "get", refuse_listitem)
    monkeypatch.setattr(scanner, "_sp_sleep", lambda s: None)
    scanner._sp_list("tok", 50000, sites=SITES, scope_out={})
    # Three strikes, and each one is retried by _sp_get's 5xx policy before it counts as a
    # failure — so the bound is "a small constant", not "one call".
    assert t.calls["per_item"] < 50, f"the breaker did not trip: {t.calls['per_item']} calls"


# ── the estate the scale run produces is still the right one ─────────────────────────────────

def test_one_budget_across_thirty_sites_not_thirty_budgets(monkeypatch):
    """Phase 1's promise, measured at scale: the cap bounds the WHOLE run. Thirty copies of it
    would be thirty times the load against a customer's tenant for one scan."""
    t = _Tenant(docs=100)
    files, scope = _scan(monkeypatch, t, max_files=500)
    assert len(files) == 500, f"the shared budget was multiplied per site: {len(files)}"
    assert scope["inventory"]["truncated"] is True


def test_thirty_sites_report_thirty_rows_and_the_totals_add_up(monkeypatch):
    """Auditable per-site totals, at the scale the exit gate is about. A grand total with no
    per-site breakdown cannot show that no site was silently omitted."""
    inv: list = []
    t = _Tenant(docs=20, libs=2, media=3)
    files, scope = _scan(monkeypatch, t, inventory=inv)
    rows = {s["id"]: s for s in scope["sites"]}
    assert len(rows) == 30 and all(r["status"] == "complete" for r in rows.values())
    assert sum(r["listed"] for r in rows.values()) == len(files) == 30 * 2 * 20
    assert sum(r["estate"] for r in rows.values()) == 30 * 2 * 23
    assert len(inv) == 30 * 2 * 3


def test_the_same_estate_twice_is_the_same_estate(monkeypatch):
    """Reproducibility at scale, including the truncation boundary — the half that depends on
    order. A count an operator cannot reproduce is worse than a slow scan."""
    first, _ = _scan(monkeypatch, _Tenant(docs=40, libs=2), max_files=900)
    second, _ = _scan(monkeypatch, _Tenant(docs=40, libs=2), max_files=900)
    assert [f["id"] for f in first] == [f["id"] for f in second]


def test_concurrency_does_not_change_the_estate_at_scale(monkeypatch):
    """test_sp_concurrency proves this on a small fixture. At 30 sites the sliding window is
    actually sliding, and the truncation boundary is decided while several walks are in flight."""
    monkeypatch.setenv("ACP_SP_CONCURRENCY", "1")
    serial, s_scope = _scan(monkeypatch, _Tenant(docs=40, libs=2), max_files=900)
    monkeypatch.setenv("ACP_SP_CONCURRENCY", "6")
    parallel, p_scope = _scan(monkeypatch, _Tenant(docs=40, libs=2), max_files=900)
    assert [f["id"] for f in serial] == [f["id"] for f in parallel]
    assert ([(s["id"], s["status"], s["listed"]) for s in s_scope["sites"]]
            == [(s["id"], s["status"], s["listed"]) for s in p_scope["sites"]])
