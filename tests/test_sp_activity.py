"""Access is not use: whether anybody has actually opened a document lately.

`collaborator_count` (#1361) says who CAN open a document. It cannot say whether anybody HAS, and
for archival those are different questions with opposite answers on the same file: a document
twelve people can reach and nobody has opened since 2019 is the candidate; one person with sole
access who reads it every week is not. `docs/sharepoint-gaps.md` named this as the part the
collaborator row did NOT cover, rather than letting that row read as complete.

Graph's item analytics is the surface. `/analytics/lastSevenDays` — one call, no date maths, and
the question is "has anybody touched this at all lately", not a timeline. Seven days is Graph's
own window and not a choice ACP made, which is why the field is named `recent_*` and the window is
recorded beside the counts.

THE ONE THING THAT MUST NOT HAPPEN. `recent_actor_count == 0` has to mean "Graph said nobody" and
never "we could not ask". Analytics is not served for every item or tenant — a personal OneDrive,
a library with reporting off, an item too new to have a rollup — and a rule reading "nobody has
opened this in seven days" off a count that is really an unanswered question would archive a live
estate. Every test below that looks like paranoia is that one case.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import disposition  # noqa: E402
import scanner  # noqa: E402
import sp_metadata as M  # noqa: E402

ITEM = {"id": "i1", "name": "policy.docx", "file": {"mimeType": "x"},
        "createdBy": {"user": {"displayName": "Alice"}},
        "lastModifiedBy": {"user": {"displayName": "Alice"}}}


def _fields(analytics=None):
    return M.normalize(ITEM, list_item=M.Container.missing("no expansion"), drive_item=None,
                       rich=None, permissions=None, analytics=analytics,
                       site_id="S1", site_name="Finance", library_name="Documents")["fields"]


# ── the counts, and the state they carry ─────────────────────────────────────────────────────

def test_an_active_document_reports_who_touched_it():
    f = _fields(M.Container({"access": {"actorCount": 3, "actionCount": 11}}))
    assert (f["recent_actor_count"]["value"], f["recent_actor_count"]["state"]) == (3, M.PRESENT)
    assert f["recent_action_count"]["value"] == 11


def test_a_payload_that_arrived_with_no_access_facet_is_a_real_zero():
    """Graph served analytics for this item and nothing was recorded in the window. That IS the
    idle answer, and it is the one an archival rule is allowed to act on."""
    f = _fields(M.Container({}))
    assert f["recent_actor_count"]["value"] == 0
    assert f["recent_actor_count"]["state"] == M.PRESENT


def test_NOT_REQUESTED_IS_NOT_ZERO():
    """THE CASE THE WHOLE FIELD TURNS ON. Off by default, so every document on every scan that
    has not opted in reports unavailable — with the switch named — rather than looking idle."""
    f = _fields()
    assert f["recent_actor_count"]["value"] is None
    assert f["recent_actor_count"]["state"] == M.UNAVAILABLE
    assert "ACP_SP_ANALYTICS=1" in f["recent_actor_count"]["reason"]


def test_the_container_state_beats_any_value_a_caller_passes():
    """WHY the case above cannot regress, pinned at the mechanism rather than at one field.

    A first version of this test asserted that `normalize` does not default the count to 0 — and
    it could not fail, because `resolve` discards the value outright when the container was not
    read. The protection is structural, not a caller being careful, and a test that claims
    otherwise is describing a discipline nobody has to keep.

    So this pins `resolve`'s own ordering: an unread container is `unavailable` even when the
    caller hands it a perfectly good number. That is the line that stops an unmeasurable estate
    reading as an idle one."""
    assert M.resolve(M.Container.missing("not asked"), 0)["state"] == M.UNAVAILABLE
    assert M.resolve(M.Container.missing("not asked"), 0)["value"] is None
    assert M.resolve(M.Container.missing("not asked"), 99)["value"] is None
    # And a genuine zero from a container that WAS read survives as a value, rather than being
    # swept into `not_configured` with the empty string and the empty list.
    assert M.resolve(M.Container({}), 0) == {"value": 0, "state": M.PRESENT, "reason": None}


def test_both_activity_fields_are_resolved_against_the_analytics_container():
    """Asserted against the source because the container is the whole guarantee: a field that
    resolved against `drive_item` instead would report `not_configured` on a tenant that was
    never asked — the exact sentence "the tenant records no activity" for an unmeasured file."""
    import inspect
    src = inspect.getsource(M.normalize)
    for field in ("recent_actor_count", "recent_action_count"):
        line = next(l for l in src.splitlines() if f'"{field}": resolve(' in l)
        assert "resolve(ana," in line, f"{field} is not resolved against the analytics container"


def test_a_tenant_that_does_not_serve_analytics_is_unavailable_not_idle():
    f = _fields(M.Container.missing("this drive does not serve item analytics"))
    assert f["recent_actor_count"]["value"] is None
    assert f["recent_actor_count"]["state"] == M.UNAVAILABLE


def test_the_window_is_recorded_because_it_is_graphs_and_not_ours():
    assert M.ANALYTICS_WINDOW_DAYS == 7


def test_a_malformed_payload_does_not_crash_the_record():
    for junk in ({"access": "not-a-dict"}, {"access": {"actorCount": "x"}}, {"access": None}):
        f = _fields(M.Container(junk))
        assert isinstance(f["recent_actor_count"]["value"], int)


# ── the rule ─────────────────────────────────────────────────────────────────────────────────

DEAD = [{"field": "modified_age_days", "op": "gt", "value": 2555},
        {"field": "collaborator_count", "op": "lte", "value": 1},
        {"field": "recent_actor_count", "op": "eq", "value": 0}]


def _doc(**over):
    return {"source_modified": "2015-01-01T00:00:00+00:00", "collaborator_count": 1, **over}


def test_an_old_untouched_document_is_flagged():
    assert disposition.matches(_doc(recent_actor_count=0), DEAD) is True


def test_an_old_document_somebody_still_opens_is_not():
    """The whole point. Age and access both say archive; use says no."""
    assert disposition.matches(_doc(recent_actor_count=4), DEAD) is False


def test_an_UNMEASURED_document_is_not_flagged():
    """A rule keyed on activity must match nothing on an estate that was never measured — not
    everything. This is the `None` that would have been a 0."""
    assert disposition.matches(_doc(recent_actor_count=None), DEAD) is False
    assert disposition.matches(_doc(), DEAD) is False


def test_both_counts_are_declared_rule_fields():
    assert {"recent_actor_count", "recent_action_count"} <= disposition.FIELDS


def test_the_counts_survive_the_trip_to_the_rule_engine():
    import json

    import handlers
    meta = _fields(M.Container({"access": {"actorCount": 2, "actionCount": 9}}))
    row = scanner._inv_row(file="policy.docx", sp_meta={"fields": meta})
    blob = json.loads(row["sp_metadata"])
    assert blob["activity"] == {"actors": 2, "actions": 9, "window_days": 7}
    inputs = handlers._sp_rule_inputs({"sp_metadata": row["sp_metadata"]})
    assert inputs["recent_actor_count"] == 2 and inputs["recent_action_count"] == 9


def test_an_unmeasured_row_carries_no_count_to_the_engine():
    import handlers
    row = scanner._inv_row(file="policy.docx", sp_meta={"fields": _fields()})
    inputs = handlers._sp_rule_inputs({"sp_metadata": row["sp_metadata"]})
    assert inputs["recent_actor_count"] is None


# ── the enrichment pass ──────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _tenant(docs=3, *, analytics_status=200, seen=None):
    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        if "/analytics" in url:
            if analytics_status != 200:
                return _Resp({}, analytics_status)
            return _Resp({"access": {"actorCount": 5, "actionCount": 9}})
        if "/sites/" in url and "/drives" in url:
            return _Resp({"value": [{"id": "d1", "name": "Documents"}]})
        if "/children" in url:
            if "expand=listItem" in url or "retentionLabel" in url:
                return _Resp({}, 400)
            return _Resp({"value": [{"id": f"i{n}", "name": f"doc{n}.docx", "file": {}}
                                    for n in range(docs)]})
        return _Resp({"displayName": "Finance"})
    return get


def _run(monkeypatch, tenant):
    import httpx
    monkeypatch.setattr(httpx, "get", tenant)
    scope: dict = {}
    return scanner._sp_list("tok", 5000, sites=["S1"], scope_out=scope), scope


def _actors(rec):
    return rec["sp_metadata"]["fields"]["recent_actor_count"]


def test_off_by_default_nothing_is_spent_and_nothing_reads_idle(monkeypatch):
    seen: list = []
    files, scope = _run(monkeypatch, _tenant(seen=seen))
    assert not [u for u in seen if "/analytics" in u]
    assert all(_actors(f)["state"] == M.UNAVAILABLE for f in files)
    assert "activity_read" not in scope


def test_turning_it_on_fills_the_counts(monkeypatch):
    monkeypatch.setenv("ACP_SP_ANALYTICS", "1")
    files, scope = _run(monkeypatch, _tenant())
    assert all(_actors(f)["value"] == 5 for f in files)
    assert scope["activity_read"]["read"] == 3


def test_the_read_is_budgeted(monkeypatch):
    """Third per-document read in this connector, third budget. One call per document is what
    tests/test_sp_scale.py exists to keep out of a 30-site walk."""
    monkeypatch.setenv("ACP_SP_ANALYTICS", "1")
    monkeypatch.setenv("ACP_SP_ANALYTICS_MAX", "2")
    seen: list = []
    files, scope = _run(monkeypatch, _tenant(docs=10, seen=seen))
    assert len([u for u in seen if "/analytics" in u]) == 2
    assert scope["activity_read"]["capped"] is True


def test_what_the_budget_costs_is_the_FIELD_not_a_false_zero(monkeypatch):
    """A document past the cap must report unavailable, so an activity rule skips it. Reporting
    0 would archive it on a measurement that never happened."""
    monkeypatch.setenv("ACP_SP_ANALYTICS", "1")
    monkeypatch.setenv("ACP_SP_ANALYTICS_MAX", "1")
    files, _ = _run(monkeypatch, _tenant(docs=3))
    states = sorted((_actors(f)["state"], _actors(f)["value"]) for f in files)
    assert states == [(M.PRESENT, 5), (M.UNAVAILABLE, None), (M.UNAVAILABLE, None)]


def test_a_tenant_that_refuses_analytics_leaves_it_unavailable(monkeypatch):
    """A 404 there means "we cannot ask" — not "nobody touched it"."""
    monkeypatch.setenv("ACP_SP_ANALYTICS", "1")
    monkeypatch.setattr(scanner, "_sp_sleep", lambda s: None)
    files, _ = _run(monkeypatch, _tenant(docs=2, analytics_status=404))
    assert all(_actors(f)["state"] == M.UNAVAILABLE for f in files)


def test_an_analytics_failure_never_fails_the_scan(monkeypatch):
    monkeypatch.setenv("ACP_SP_ANALYTICS", "1")
    monkeypatch.setattr(scanner, "_sp_sleep", lambda s: None)
    files, _ = _run(monkeypatch, _tenant(docs=2, analytics_status=500))
    assert [f["name"] for f in files] == ["doc0.docx", "doc1.docx"]


def test_the_budget_survives_a_nonsense_value(monkeypatch):
    assert scanner._sp_analytics_budget() == 1000
    monkeypatch.setenv("ACP_SP_ANALYTICS_MAX", "junk")
    assert scanner._sp_analytics_budget() == 1000
    monkeypatch.setenv("ACP_SP_ANALYTICS_MAX", "-1")
    assert scanner._sp_analytics_budget() == 0


def test_the_export_carries_the_counts_and_leaves_them_blank_when_unmeasured():
    """An empty cell must be readable as "not measured" — `sp_availability` carries the state
    beside it, the same way it does for every other SharePoint column."""
    from routes.scans import _sp_export_cells
    measured = scanner._inv_row(file="p.docx", sp_meta={"fields": _fields(
        M.Container({"access": {"actorCount": 4, "actionCount": 6}}))})
    assert _sp_export_cells(measured["sp_metadata"])["recent_actor_count"] == 4
    unmeasured = scanner._inv_row(file="p.docx", sp_meta={"fields": _fields()})
    assert _sp_export_cells(unmeasured["sp_metadata"])["recent_actor_count"] is None
