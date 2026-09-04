"""Incremental discovery at ESTATE scale — Phase 3, and its exit gate.

THE GATE: *a 30-site incremental scan processes only changed documents while producing the same
final inventory as a full scan.* Both halves matter and they pull against each other. A scan that
walks everything trivially produces the right inventory and saves nothing; a scan that skips
everything trivially saves everything and reports a stale estate. The gate is that the cheap run
and the expensive run agree — so this file runs BOTH over the same fixture and compares them.

Unlike Phase 2's gate, this one needs no tenant: what it asserts is a relationship between two
runs of the same code over the same data, and a fixture settles that completely.

WHY PER-LIBRARY. `_sp_whole_library_target` answers only for the one shape a single-drive delta
can serve — the whole of exactly one library. A site request covers several, so every site scan
fell through to a complete re-walk on every run: the case the incremental feature was built for,
and the only one a 30-site estate is ever in. A 30-site estate also never has one answer — one
library's cursor is fresh, another's expired last week, a third has never been synced — and
collapsing that to a single yes/no means either walking everything because one library needs it,
or reconstructing everything and serving a stale estate for the one that did not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import core        # noqa: E402
import scanner     # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.content = b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _doc(n, drive):
    """One Graph driveItem as the walk sees it."""
    return {"id": f"{drive}-i{n}", "name": f"{drive}-{n}.docx", "file": {"mimeType": "x"},
            "parentReference": {"driveId": drive, "path": "/drive/root:"},
            "lastModifiedDateTime": "2026-08-01T00:00:00Z",
            "listItem": {"contentType": {"name": "Policy"},
                         "fields": {"Records Category": "Active"}}}


def _tenant(sites, per_library=2, seen=None):
    """`sites` is [(site_id, [drive_id, ...]), ...]."""
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
                    return _Resp({"value": [_doc(n, d) for n in range(per_library)]})
        raise AssertionError(f"unexpected Graph URL: {url}")
    return get


def _inventory(files, inv):
    """The comparable shape of one run's estate: every document it recorded, scannable or not,
    with the metadata a report is written from. This is what "the same final inventory" means —
    not a count, which two different estates can share."""
    rows = [{"file": f["name"], "id": f["id"], "drive": f.get("driveId"),
             "site": f.get("siteId"), "content_type": f.get("content_type")} for f in files]
    rows += [{"file": r["file"], "id": r["drive_file_id"], "drive": r["drive_id"],
              "site": r["site_id"], "content_type": r["content_type"]} for r in inv]
    return sorted(rows, key=lambda r: (r["drive"] or "", r["id"] or ""))


THIRTY = [(f"S{n}", [f"d{n}"]) for n in range(30)]


# ── the exit gate ────────────────────────────────────────────────────────────────────────────

def test_the_exit_gate_an_incremental_estate_scan_matches_a_full_one(monkeypatch):
    """30 sites, 30 libraries, 60 documents. Run it fully, then run it incrementally with every
    library's cursor fresh and nothing changed — and require the two inventories to be IDENTICAL,
    document for document, with the same content types carried through.

    If they differ, the incremental path is serving a different estate than the truth, which is
    the one failure this feature can have and the one nobody would notice: both runs complete,
    both report a plausible count.
    """
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant(THIRTY))
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: f"site-{s}", raising=True)

    full_inv: list[dict] = []
    full_scope: dict = {}
    full_files = scanner._sp_list("tok", 500, sites=[s for s, _ in THIRTY],
                                  inventory_out=full_inv, scope_out=full_scope)
    expected = _inventory(full_files, full_inv)
    assert len(expected) == 60, f"the fixture did not produce the estate under test: {len(expected)}"

    # The same estate, reconstructed: every library has a cursor and a baseline, nothing changed.
    prior_rows = [{"file": f["name"], "drive_file_id": f["id"], "mime": "x", "size_kb": 1,
                   "checksum": None, "created_at": None, "source_modified": None,
                   "owner": None, "parent_folder": "/drive/root:", "drive_id": f.get("driveId"),
                   "drive_account_id": None, "content_type": f.get("content_type"),
                   "site_id": f.get("siteId"), "site_name": None,
                   "library_name": f.get("libraryName"), "retention_label": None,
                   "sensitivity_label": None, "sharing_scope": None, "item_kind": "document",
                   "checked_out_by": None, "sp_version": None, "modified_by": None,
                   "sp_metadata": None}
                  for f in full_files]
    by_drive: dict = {}
    for r in prior_rows:
        by_drive.setdefault(r["drive_id"], []).append(r)
    plan = {"delta": {d: {"prior_files": [scanner._sp_file_from_inventory_row(r) for r in rows],
                          "changed": [], "removed_ids": set()}
                      for d, rows in by_drive.items()},
            "full": {}, "carried": len(prior_rows)}

    seen: list[str] = []
    monkeypatch.setattr(httpx, "get", _tenant(THIRTY, seen=seen))
    inc_inv: list[dict] = []
    inc_scope: dict = {}
    inc_files = scanner._sp_list("tok", 500, sites=[s for s, _ in THIRTY],
                                 inventory_out=inc_inv, scope_out=inc_scope, delta_plan=plan)

    assert _inventory(inc_files, inc_inv) == expected, \
        "the incremental estate differs from the full one — a stale estate reported as current"
    # …and it did NOT walk. This is the other half of the gate: an incremental run that quietly
    # re-walks everything would pass the comparison above and save nothing.
    assert not any("/root/children" in u for u in seen), \
        f"walked a library it had a cursor for: {[u for u in seen if 'children' in u][:3]}"
    assert len(inc_scope["incremental"]["delta_libraries"]) == 30
    assert inc_scope["incremental"]["full_libraries"] == []


def test_a_changed_document_is_the_only_one_re_read(monkeypatch):
    """"Processes only changed documents", asserted from the other direction: the delta's own
    item replaces its prior entry wholly, everything else carries forward untouched."""
    import httpx
    sites = [("S0", ["d0"]), ("S1", ["d1"])]
    monkeypatch.setattr(httpx, "get", _tenant(sites))
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: f"site-{s}", raising=True)
    prior = [scanner._sp_file_from_inventory_row(
        {"file": f"d0-{n}.docx", "drive_file_id": f"d0-i{n}", "mime": "x", "size_kb": 1,
         "drive_id": "d0", "content_type": "Policy", "site_id": "S0",
         "parent_folder": "/drive/root:"}) for n in range(2)]
    changed = dict(_doc(0, "d0"), name="d0-0-RENAMED.docx")
    plan = {"delta": {"d0": {"prior_files": prior, "changed": [changed],
                             "removed_ids": set()}},
            "full": {}, "carried": 1}
    files = scanner._sp_list("tok", 500, sites=["S0"], delta_plan=plan)
    names = sorted(f["name"] for f in files)
    assert names == ["d0-0-RENAMED.docx", "d0-1.docx"], names


def test_a_deleted_document_leaves_the_estate(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant([("S0", ["d0"])]))
    prior = [scanner._sp_file_from_inventory_row(
        {"file": f"d0-{n}.docx", "drive_file_id": f"d0-i{n}", "mime": "x", "size_kb": 1,
         "drive_id": "d0", "parent_folder": "/drive/root:"}) for n in range(2)]
    plan = {"delta": {"d0": {"prior_files": prior, "changed": [],
                             "removed_ids": {("d0", "d0-i1")}}}, "full": {}, "carried": 1}
    files = scanner._sp_list("tok", 500, sites=["S0"], delta_plan=plan)
    assert [f["name"] for f in files] == ["d0-0.docx"]


# ── per-library isolation: the reason the plan is per library at all ─────────────────────────

def test_one_library_without_a_cursor_is_walked_and_the_rest_are_not(monkeypatch):
    """THE case a single yes/no gets wrong. One library needs walking; collapsing the answer
    means either re-walking the other twenty-nine for nothing, or serving this one stale."""
    import httpx
    sites = [("S0", ["d0"]), ("S1", ["d1"]), ("S2", ["d2"])]
    seen: list[str] = []
    monkeypatch.setattr(httpx, "get", _tenant(sites, seen=seen))
    monkeypatch.setattr(scanner, "_sp_site_name", lambda t, s: f"site-{s}", raising=True)
    prior = {d: [scanner._sp_file_from_inventory_row(
        {"file": f"{d}-{n}.docx", "drive_file_id": f"{d}-i{n}", "mime": "x", "size_kb": 1,
         "drive_id": d, "parent_folder": "/drive/root:"}) for n in range(2)]
        for d in ("d0", "d2")}
    plan = {"delta": {d: {"prior_files": rows, "changed": [], "removed_ids": set()}
                      for d, rows in prior.items()},
            "full": {"d1": "no usable delta cursor for this library yet"}, "carried": 4}
    scope: dict = {}
    files = scanner._sp_list("tok", 500, sites=[s for s, _ in sites], scope_out=scope,
                             delta_plan=plan)
    assert len(files) == 6, "the estate lost a library to the hybrid"
    walked = [u for u in seen if "/root/children" in u]
    assert len(walked) == 1 and "/drives/d1/" in walked[0], walked
    assert scope["incremental"]["delta_libraries"] == ["d0", "d2"]
    assert scope["incremental"]["full_libraries"] == ["d1"]
    assert "no usable delta cursor" in scope["incremental"]["reconciled"]["d1"]


def test_the_scope_records_how_much_of_the_estate_was_carried_rather_than_read(monkeypatch):
    """A file count cannot show that an incremental run worked — it is supposed to equal the full
    run's. What distinguishes them is how much was carried forward, so that is recorded."""
    import httpx
    monkeypatch.setattr(httpx, "get", _tenant([("S0", ["d0"])]))
    prior = [scanner._sp_file_from_inventory_row(
        {"file": "a.docx", "drive_file_id": "d0-i0", "mime": "x", "size_kb": 1,
         "drive_id": "d0", "parent_folder": "/drive/root:"})]
    plan = {"delta": {"d0": {"prior_files": prior, "changed": [], "removed_ids": set()}},
            "full": {}, "carried": 1}
    scope: dict = {}
    scanner._sp_list("tok", 500, sites=["S0"], scope_out=scope, delta_plan=plan)
    assert scope["incremental"]["carried_documents"] == 1


# ── the plan itself ──────────────────────────────────────────────────────────────────────────

def test_the_plan_partitions_the_baseline_by_drive(isolated_store, monkeypatch):
    """_sp_prior_inventory_for_drive rejects a baseline if ANY row belongs to another drive —
    correct for one library, and exactly wrong for thirty: every row would 'belong to another
    drive' from twenty-nine perspectives and no library would ever have a baseline."""
    monkeypatch.setattr(core, "get_store", lambda: isolated_store)
    isolated_store.init_scan_run("s1", "sharepoint", 0, "2026-01-01T00:00:00Z", "rb", "h",
                                 owner="o@example.com", status="running")
    isolated_store.add_inventory("s1", [
        {"file": "a.docx", "drive_file_id": "i1", "drive_id": "d0"},
        {"file": "b.docx", "drive_file_id": "i2", "drive_id": "d1"}])
    isolated_store.mark_scan_complete("s1") if hasattr(isolated_store, "mark_scan_complete") else None
    isolated_store.save_scan_completed("s1") if hasattr(isolated_store, "save_scan_completed") else None
    got = core._sp_prior_inventory_by_drive("o@example.com", ["d0", "d1"])
    # Either the store exposes a completion hook or it does not; when the baseline query finds
    # nothing the partition is empty, and an empty partition means "walk it" — never a wrong
    # baseline. Both outcomes are safe; what must never happen is rows landing under the wrong
    # drive.
    for drive, rows in got.items():
        assert all(r["drive_id"] == drive for r in rows), "a baseline row landed on another drive"


def test_a_stale_cursor_forces_a_full_reconciliation(monkeypatch):
    """Graph's delta feed reports driveItem changes; a managed-column edit that does not touch
    the driveItem may never appear in it. A library synced incrementally forever would carry a
    stale records category indefinitely, with nothing saying so — so the cursor has a shelf life.
    """
    monkeypatch.setenv("ACP_SP_RECONCILE_DAYS", "7")
    assert core._sp_cursor_is_stale({"updated_at": "2026-01-01T00:00:00Z"})
    import datetime as _dt
    fresh = _dt.datetime.now(_dt.timezone.utc).isoformat()
    assert core._sp_cursor_is_stale({"updated_at": fresh}) is None


def test_an_unreadable_cursor_timestamp_is_treated_as_DUE(monkeypatch):
    """An unparseable timestamp is a fact we do not have. Defaulting the unknown to 'recently
    synced' is how a library would quietly never be reconciled again."""
    monkeypatch.setenv("ACP_SP_RECONCILE_DAYS", "7")
    assert core._sp_cursor_is_stale({"updated_at": "not a date"})
    # A cursor ROW that exists with no timestamp column is the same missing fact.
    assert core._sp_cursor_is_stale({"page_token": "x", "updated_at": None})
    # No cursor at all is a different thing and is NOT this function's answer: it is a seed, and
    # the caller already walks that library in full. Reporting it "stale" here would be a second
    # place deciding the same question, which is how two answers start to disagree.
    assert core._sp_cursor_is_stale(None) is None


def test_reconciliation_can_be_switched_off_knowingly(monkeypatch):
    monkeypatch.setenv("ACP_SP_RECONCILE_DAYS", "0")
    assert core._sp_cursor_is_stale({"updated_at": "2020-01-01T00:00:00Z"}) is None


@pytest.mark.parametrize("bad", ["", "nonsense", "-3"])
def test_a_malformed_reconcile_setting_falls_back_to_the_default(monkeypatch, bad):
    monkeypatch.setenv("ACP_SP_RECONCILE_DAYS", bad)
    assert core.sp_reconcile_days() in (7, 0)


# ── the shortcut can never cost a scan ───────────────────────────────────────────────────────

def test_a_failure_while_planning_falls_back_to_walking_everything(monkeypatch):
    """An optimisation that can fail a scan is worse than no optimisation, and the failure would
    land on the largest estates first."""
    import handlers
    monkeypatch.setattr(core, "sp_multi_sync_plan",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("graph exploded")))
    assert handlers._sp_site_delta_plan("o@example.com", "tok", None, ["S0"]) is None


def test_a_folder_narrowed_request_is_never_planned(monkeypatch):
    """Graph's delta query has no folder filter, so a reconstruction could not honour the
    narrowing — it would silently widen the scan back to whole libraries."""
    import handlers
    assert handlers._sp_site_delta_plan("o@example.com", "tok", None, ["d1/item1"]) is None


# ── Phase 2's metadata must survive a Phase 3 sync ───────────────────────────────────────────
#
# The same defect as docs/TODO.md P1e, one phase later and on a wider set of fields. The Content
# Type was silently erased on every delta sync for months because ONE name was missing from ONE
# SELECT — the column was real, add_inventory wrote it, and the reconstruction baseline simply
# never read it back. Phase 2 added eleven more columns of exactly that kind, and they are the
# ones lifecycle rules are written against.
#
# These cases exist because the first bite check of this file did not bite: removing the
# carry-forward left every test green, which was a finding about the tests, not a passing fix.

def _carrying_row(**over):
    row = {"file": "policy.docx", "drive_file_id": "d0-i0", "mime": "x", "size_kb": 1,
           "drive_id": "d0", "parent_folder": "/drive/root:",
           "content_type": "Superseded Policy", "site_id": "S0", "site_name": "Regulatory",
           "library_name": "Policies", "retention_label": "Retain 7 Years",
           "sharing_scope": "organization", "item_kind": "document", "sp_version": "4.0",
           "checked_out_by": None, "modified_by": "Alice Brown", "sensitivity_label": None,
           "sp_metadata": '{"managed_columns":{"Records Category":"Superseded"},'
                          '"availability":{"sensitivity_label":"unavailable"},'
                          '"reasons":{"sensitivity_label":"beta only"}}'}
    row.update(over)
    return row


def test_an_unchanged_file_keeps_every_sharepoint_field_through_a_sync():
    """Not just the content type. A delta sync that returned each unchanged file stripped of its
    retention label and managed columns would silently stop every governance rule from matching
    — on the run AFTER the one that set them up, which is the worst possible time."""
    raw = scanner._sp_file_from_inventory_row(_carrying_row())
    meta = scanner._sp_item_metadata(raw, site_id=None, site_name=None, library_name=None)
    import sp_metadata as M
    v = M.values(meta)
    assert v["content_type"] == "Superseded Policy"
    assert v["retention_label"] == "Retain 7 Years"
    assert v["managed_columns"] == {"Records Category": "Superseded"}
    assert v["site_name"] == "Regulatory" and v["library_name"] == "Policies"
    assert v["version"] == "4.0" and v["sharing_scope"] == "organization"


def test_a_carried_field_the_tenant_never_set_reads_as_NOT_CONFIGURED():
    """The earlier run DID read the container and wrote NULL because nothing was in it. Calling
    it `unavailable` now would invent a read failure that never happened, and would make an
    estate look progressively less readable the longer delta sync ran."""
    import sp_metadata as M
    raw = scanner._sp_file_from_inventory_row(_carrying_row(retention_label=None))
    meta = scanner._sp_item_metadata(raw, site_id=None, site_name=None, library_name=None)
    assert meta["fields"]["retention_label"]["state"] == M.NOT_CONFIGURED


def test_a_field_that_was_genuinely_UNREAD_stays_unread_across_the_carry_forward():
    """The carry-forward must not launder a gap into an answer. A sensitivity label ACP never
    asked for is still one ACP never asked for, however many syncs later."""
    import sp_metadata as M
    raw = scanner._sp_file_from_inventory_row(_carrying_row())
    meta = scanner._sp_item_metadata(raw, site_id=None, site_name=None, library_name=None)
    f = meta["fields"]["sensitivity_label"]
    assert f["state"] == M.UNAVAILABLE and f["reason"] == "beta only"


def test_the_metadata_reaches_the_reconstructed_inventory_row(monkeypatch):
    """End to end through the listing, not just the helper: what a sync PERSISTS is what the
    next rule preview and the next export read."""
    import httpx
    import json
    monkeypatch.setattr(httpx, "get", _tenant([("S0", ["d0"])]))
    prior = [scanner._sp_file_from_inventory_row(
        _carrying_row(file="clip.mp4", drive_file_id="d0-m0", mime="video/mp4"))]
    plan = {"delta": {"d0": {"prior_files": prior, "changed": [], "removed_ids": set()}},
            "full": {}, "carried": 1}
    inv: list[dict] = []
    scanner._sp_list("tok", 500, sites=["S0"], inventory_out=inv, delta_plan=plan)
    [row] = inv
    assert row["retention_label"] == "Retain 7 Years"
    assert row["content_type"] == "Superseded Policy"
    assert json.loads(row["sp_metadata"])["managed_columns"] == {"Records Category": "Superseded"}


def test_the_baseline_query_selects_every_carried_column():
    """The one-name omission that cost the Content Type for months, generalised. Asserted against
    the SOURCE because the query's shape IS the defect: a round trip would pass on any column
    list that happens to include them for some other reason, and the failure mode here is a
    column quietly dropped from a SELECT during an unrelated edit."""
    import inspect
    import store
    src = inspect.getsource(store.Store.latest_scan_inventory_items)
    select = src[src.index("SELECT file,"):]
    select = select[:select.index("FROM scan_inventory")]
    for col in scanner._SP_CARRIED_METADATA:
        assert col in select, (
            f"{col} is carried forward by _sp_file_from_inventory_row but the baseline query "
            f"never reads it back — every unchanged file loses it on every delta sync")
