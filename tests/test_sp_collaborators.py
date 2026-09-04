"""Smart archival: check who is still working on a document before flagging it (the SOW's row).

"Archive anything older than seven years" is a rule that eventually archives something a team is
still using. The SOW asks for the check that stops it, and `docs/sharepoint-gaps.md` carried it as
the last open gap row: *check active collaborators before flagging — not ingested*.

TWO PRECISIONS, AND THE COUNT ALONE CANNOT TELL THEM APART. That is the whole design:

  * `authorship` — the creator and the last editor, off the listing page's own `$select`. FREE on
    every tier including the bare one, and a **floor**: a document twelve people edited names two
    of them, because a driveItem records the first and the most recent and nothing between.
  * `permissions` — everyone with access, from the item's permissions collection. Accurate, and
    one Graph call per document.

So `collaborator_count` never travels without `collaborator_basis`. A floor of 1 is a sound
archival signal and says something true (one person made it, nobody else ever touched it); a floor
of 2 says almost nothing; and reporting either as a total is the overstatement the pair exists to
prevent. A rule written `collaborator_count <= 1` is correct under both bases, which is why the
free floor was worth shipping rather than withholding until permissions are switched on.

AND A SWITCH THAT WAS LYING. `sp_metadata.permissions_enabled()` shipped in Phase 2 with no
caller: `ACP_SP_PERMISSIONS=1` did nothing, while the `permissions` field's own reason string told
the operator to set it. A documented switch that does nothing is worse than an undocumented gap —
it ends the search for why the field is empty. It is wired here, off by default and budgeted when
on, because one call per document is exactly the cost `tests/test_sp_scale.py` exists to keep out
of a 30-site walk.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import disposition  # noqa: E402
import scanner  # noqa: E402
import sp_metadata as M  # noqa: E402


def _u(name):
    return {"user": {"displayName": name}}


def _item(created="Alice", modified="Bob"):
    return {"id": "i1", "name": "policy.docx", "file": {"mimeType": "x"},
            "createdBy": _u(created) if created else None,
            "lastModifiedBy": _u(modified) if modified else None}


def _meta(item, permissions=None):
    return M.normalize(item, list_item=M.Container.missing("no expansion"), drive_item=None,
                       rich=None, permissions=permissions,
                       site_id="S1", site_name="Finance", library_name="Documents")


def _field(item, name, permissions=None):
    return _meta(item, permissions)["fields"][name]


# ── the free floor ───────────────────────────────────────────────────────────────────────────

def test_one_author_who_is_also_the_last_editor_counts_as_one():
    """THE ARCHIVAL SIGNAL. One person made it, nobody else ever touched it — the case a
    date-only rule is safe to act on and the reason the floor is worth having at all."""
    f = _field(_item(created="Alice", modified="Alice"), "collaborator_count")
    assert f["value"] == 1 and f["state"] == M.PRESENT


def test_a_different_editor_makes_two():
    assert _field(_item(created="Alice", modified="Bob"), "collaborator_count")["value"] == 2


def test_an_item_naming_nobody_counts_zero_rather_than_erroring():
    assert _field(_item(created=None, modified=None), "collaborator_count")["value"] == 0


def test_the_floor_says_it_is_a_floor():
    assert _field(_item(), "collaborator_basis")["value"] == M.BASIS_AUTHORSHIP


def test_the_floor_costs_nothing_because_it_reads_the_BASE_select():
    """`createdBy` and `lastModifiedBy` are in the walk's base `$select`, so the signal survives
    a tenant that refuses both the wide select and the listItem expansion — the tier-2 tenant
    that has the least metadata is the one most in need of an archival input that still works."""
    assert "createdBy" in scanner._SP_ITEM_SELECT and "lastModifiedBy" in scanner._SP_ITEM_SELECT


# ── the accurate count ───────────────────────────────────────────────────────────────────────

def test_the_permissions_collection_counts_distinct_people():
    perms = M.Container({"value": [
        {"grantedToV2": _u("Alice")},
        {"grantedToIdentitiesV2": [_u("Carol"), _u("Dan")]},
        {"grantedToV2": _u("Alice")},                      # the same person twice
    ]})
    f = _field(_item(), "collaborator_count", permissions=perms)
    assert f["value"] == 3
    assert _field(_item(), "collaborator_basis", permissions=perms)["value"] == M.BASIS_PERMISSIONS


def test_the_older_singular_grantedTo_shape_is_read_too():
    """Some tenants still answer with it. Counting only the documented-current shape would report
    a widely shared file as having nobody on it — wrong in the direction that archives a live
    document."""
    perms = M.Container({"value": [{"grantedTo": _u("Erin")}]})
    assert _field(_item(), "collaborator_count", permissions=perms)["value"] == 1


def test_an_anonymous_link_is_not_counted_as_a_person():
    """A link with no identities grants access to people this collection cannot name. Counting it
    as zero people is right; `sharing_scope` is the field that says the file is shared, and it is
    read for free. Conflating them would turn "shared with everyone" into "nobody has access" —
    exactly backwards, and it archives."""
    perms = M.Container({"value": [{"link": {"scope": "anonymous"}}]})
    assert _field(_item(), "collaborator_count", permissions=perms)["value"] == 0


def test_a_permissions_read_that_returned_NOTHING_is_still_a_read():
    """An empty collection is a real answer about an item nobody was granted anything on, and it
    reports as `permissions`, not as the floor."""
    f = _meta(_item(), M.Container({"value": []}))["fields"]
    assert f["collaborator_count"]["value"] == 0
    assert f["collaborator_basis"]["value"] == M.BASIS_PERMISSIONS


# ── the count is a rule input ────────────────────────────────────────────────────────────────

SMART = [{"field": "modified_age_days", "op": "gt", "value": 2555},
         {"field": "collaborator_count", "op": "lte", "value": 1}]


def _doc(count, basis=M.BASIS_AUTHORSHIP):
    return {"source_modified": "2015-01-01T00:00:00+00:00",
            "collaborator_count": count, "collaborator_basis": basis}


def test_a_dead_document_is_flagged_and_a_collaborative_one_is_not():
    """The rule the gap row is about, end to end through the engine."""
    assert disposition.matches(_doc(1), SMART) is True
    assert disposition.matches(_doc(6), SMART) is False


def test_a_rule_can_refuse_to_act_on_the_floor():
    """An operator who will not archive on a two-name approximation says so in the rule. The
    basis being a matchable field is what makes that possible without a second engine."""
    strict = SMART + [{"field": "collaborator_basis", "op": "eq", "value": M.BASIS_PERMISSIONS}]
    assert disposition.matches(_doc(1, M.BASIS_AUTHORSHIP), strict) is False
    assert disposition.matches(_doc(1, M.BASIS_PERMISSIONS), strict) is True


def test_both_fields_are_declared_rule_fields():
    """A field the engine does not declare cannot be saved in a rule; a field it declares but
    nothing populates validates, saves, and silently matches nothing forever — this repo has
    shipped that twice (doc_class/size_kb, and parent_folder on SharePoint)."""
    assert {"collaborator_count", "collaborator_basis"} <= disposition.FIELDS


def test_the_count_survives_the_trip_through_the_inventory_row():
    """Carried in the `sp_metadata` blob rather than in columns of its own — both values are
    DERIVED from fields already stored, so a pair of columns would buy a schema version for
    nothing. This is the hop that a rule input actually depends on."""
    import json
    import handlers
    meta = _meta(_item(created="Alice", modified="Alice"))
    row = scanner._inv_row(file="policy.docx", sp_meta=meta)
    blob = json.loads(row["sp_metadata"])
    assert blob["collaborators"] == {"count": 1, "basis": M.BASIS_AUTHORSHIP}
    inputs = handlers._sp_rule_inputs({"sp_metadata": row["sp_metadata"]})
    assert inputs["collaborator_count"] == 1
    assert inputs["collaborator_basis"] == M.BASIS_AUTHORSHIP


def test_a_row_with_no_sharepoint_metadata_reports_neither():
    """Every non-SharePoint source. The rule then matches nothing, which is correct — and is why
    a smart-archival rule must be scoped to the SharePoint source or paired with a basis check."""
    import handlers
    inputs = handlers._sp_rule_inputs({"sp_metadata": None})
    assert inputs.get("collaborator_count") is None


# ── the switch that was doing nothing ────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _tenant(docs=3, *, perm_status=200, seen=None):
    """One site, one library, `docs` documents, each answering a permissions read."""
    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        if "/permissions" in url:
            if perm_status != 200:
                return _Resp({}, perm_status)
            return _Resp({"value": [{"grantedToV2": _u("Alice")},
                                    {"grantedToV2": _u("Bob")},
                                    {"grantedToV2": _u("Carol")}]})
        # `/sites/<id>/drives?$select=…` — the query string is why an endswith() check on this
        # silently answered "no libraries" and made the whole fixture list nothing.
        if "/sites/" in url and "/drives" in url:
            return _Resp({"value": [{"id": "d1", "name": "Documents"}]})
        if "/children" in url:
            if "expand=listItem" in url or "retentionLabel" in url:
                return _Resp({}, 400)
            return _Resp({"value": [{"id": f"i{n}", "name": f"doc{n}.docx", "file": {},
                                     "createdBy": _u("Alice"), "lastModifiedBy": _u("Alice")}
                                    for n in range(docs)]})
        return _Resp({"displayName": "Finance"})
    return get


def _run(monkeypatch, tenant):
    import httpx
    monkeypatch.setattr(httpx, "get", tenant)
    scope: dict = {}
    files = scanner._sp_list("tok", 5000, sites=["S1"], scope_out=scope)
    return files, scope


def _count(rec):
    return rec["sp_metadata"]["fields"]["collaborator_count"]["value"]


def _basis(rec):
    return rec["sp_metadata"]["fields"]["collaborator_basis"]["value"]


def test_off_by_default_the_walk_spends_nothing_and_keeps_the_floor(monkeypatch):
    seen: list = []
    files, scope = _run(monkeypatch, _tenant(seen=seen))
    assert not [u for u in seen if "/permissions" in u], (
        "a per-document permissions call on a 30-site-shaped walk, by default")
    assert all(_count(f) == 1 and _basis(f) == M.BASIS_AUTHORSHIP for f in files)
    assert "permissions_read" not in scope


def test_turning_it_on_upgrades_the_count_AND_the_basis(monkeypatch):
    """The switch's whole promise. Before this it set nothing: `permissions_enabled()` had no
    caller anywhere, while the field's own reason string told the operator to set it."""
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    files, scope = _run(monkeypatch, _tenant())
    assert all(_count(f) == 3 and _basis(f) == M.BASIS_PERMISSIONS for f in files)
    assert scope["permissions_read"]["upgraded"] == 3


def test_the_metadata_blob_moves_WITH_the_count(monkeypatch):
    """Both halves patched together. `_sp_enrich_content_types` sets `content_type` on the record
    while the blob still reports the field unavailable; repeating that here would put two
    different collaborator counts on one document — one in the export, one in the rule."""
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    files, _ = _run(monkeypatch, _tenant(docs=1))
    row = scanner._inv_row(file="doc0.docx", sp_meta=files[0]["sp_metadata"])
    import json
    assert json.loads(row["sp_metadata"])["collaborators"] == {"count": 3,
                                                               "basis": M.BASIS_PERMISSIONS}


def test_the_read_is_budgeted(monkeypatch):
    """One Graph call per document is the cost tests/test_sp_scale.py exists to keep out of a
    30-site walk. Turning the switch on must not turn that back on without a bound."""
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    monkeypatch.setenv("ACP_SP_PERMISSIONS_MAX", "2")
    seen: list = []
    files, scope = _run(monkeypatch, _tenant(docs=10, seen=seen))
    assert len([u for u in seen if "/permissions" in u]) == 2
    assert scope["permissions_read"]["capped"] is True


def test_what_the_budget_running_out_costs_is_precision_not_the_field(monkeypatch):
    """A document past the cap keeps the free floor — a smaller number, honestly labelled — so a
    rule written `<= 1` still evaluates on it rather than silently skipping it."""
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    monkeypatch.setenv("ACP_SP_PERMISSIONS_MAX", "1")
    files, _ = _run(monkeypatch, _tenant(docs=3))
    got = sorted((_count(f), _basis(f)) for f in files)
    assert got == [(1, M.BASIS_AUTHORSHIP), (1, M.BASIS_AUTHORSHIP), (3, M.BASIS_PERMISSIONS)]


def test_an_unreadable_permissions_collection_keeps_the_floor_rather_than_reporting_zero(
        monkeypatch):
    """None and `[]` are different answers. A read that did not happen must not report "nobody
    has access", because that is the answer that archives the document."""
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    monkeypatch.setattr(scanner, "_sp_sleep", lambda s: None)
    files, _ = _run(monkeypatch, _tenant(docs=2, perm_status=403))
    assert all(_count(f) == 1 and _basis(f) == M.BASIS_AUTHORSHIP for f in files)


def test_a_permissions_failure_never_fails_the_scan(monkeypatch):
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    monkeypatch.setattr(scanner, "_sp_sleep", lambda s: None)
    files, _ = _run(monkeypatch, _tenant(docs=2, perm_status=500))
    assert [f["name"] for f in files] == ["doc0.docx", "doc1.docx"]


def test_the_switch_is_read_at_call_time(monkeypatch):
    assert M.permissions_enabled() is False
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    assert M.permissions_enabled() is True


def test_the_budget_survives_a_nonsense_value(monkeypatch):
    assert scanner._sp_permissions_budget() == 1000
    monkeypatch.setenv("ACP_SP_PERMISSIONS_MAX", "not-a-number")
    assert scanner._sp_permissions_budget() == 1000
    monkeypatch.setenv("ACP_SP_PERMISSIONS_MAX", "0")
    assert scanner._sp_permissions_budget() == 0


def test_the_export_carries_the_count_AND_the_basis():
    """A sheet showing "collaborators: 1" without saying how it was counted invites the reader to
    treat an authorship floor as a total — the same mistake the availability column exists to stop
    one field over. Both cells or neither."""
    from routes.scans import _sp_export_cells
    meta = _meta(_item(created="Alice", modified="Alice"))
    row = scanner._inv_row(file="policy.docx", sp_meta=meta)
    cells = _sp_export_cells(row["sp_metadata"])
    assert cells["collaborator_count"] == 1
    assert cells["collaborator_basis"] == M.BASIS_AUTHORSHIP


def test_a_non_sharepoint_export_row_has_neither_cell():
    from routes.scans import _sp_export_cells
    assert _sp_export_cells(None) == {}
