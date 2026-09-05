"""Scanning several chosen folders, and saying so.

A scan could be narrowed to ONE folder (Drive) or ONE site (SharePoint), and OneDrive could not
be narrowed at all. An estate is "HR and Finance", so one-at-a-time forced a choice between
scanning too much and running several scans whose counts are then added up by hand — and a total
you assembled yourself carries no recorded boundary, which is the whole failure
frontend/src/scanScope.js exists to prevent.

Every case below is here because ITS FAILURE MODE IS A PLAUSIBLE NUMBER rather than an error:

  · overlapping roots double-count, and the duplicate is renamed "Policy (1).docx" — a phantom
    document that inflates the count and is analysed twice
  · a per-root cap lets four folders list 4x the ceiling while every individual walk looks right
  · a narrowed scan that records no boundary reads as the whole estate — the 2026-07-30 defect
  · a OneDrive folder scan has NO site, so the old narrowness test could not see it at all

The Drive cases drive the real BFS through a fake service (the idiom in
test_discovery_scope_reported.py) rather than mocking our own functions, so the paging, dedupe
and normalise path is the one that runs in production.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


def _f(fid, name, mime=DOC):
    return {"id": fid, "name": name, "mimeType": mime}


class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self, **kw):
        return self._payload


class FakeFiles:
    def __init__(self, pages, names=None):
        self._pages, self._names = pages, (names or {})

    def list(self, **kw):
        q = kw.get("q", "")
        for key, pages in self._pages.items():
            if key in q:
                idx = 0 if kw.get("pageToken") is None else int(kw["pageToken"])
                return _Exec(pages[idx] if idx < len(pages) else {"files": []})
        return _Exec({"files": []})

    def get(self, fileId=None, **kw):
        return _Exec({"name": self._names.get(fileId, fileId)})


class FakeSvc:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def _svc(tree, names=None):
    return FakeSvc(FakeFiles({f"'{k}' in parents": [{"files": v}] for k, v in tree.items()},
                             names=names))


# ── the union ────────────────────────────────────────────────────────────────────────────────

def test_two_folders_are_scanned_as_one_estate():
    svc = _svc({"hr": [_f("d1", "Leave.docx")], "fin": [_f("d2", "Budget.docx")]},
               names={"hr": "HR", "fin": "Finance"})
    scope: dict = {}
    items = scanner._list("drive", svc, folders=["hr", "fin"], scope_out=scope)
    assert sorted(i["name"] for i in items) == ["Budget.docx", "Leave.docx"]
    assert scope["kept"] == 2


def test_a_file_reachable_from_two_chosen_roots_is_counted_once():
    """Picking a folder AND something inside it is an ordinary selection, not a mistake.

    Without dedupe the repeat survives to _dedupe_names, which renames it "Leave (1).docx" — a
    document that does not exist, is downloaded and analysed twice, and shows in the UI as
    "x2 copies". The count is wrong in the direction that looks like MORE coverage.
    """
    shared = _f("d1", "Leave.docx")
    svc = _svc({"hr": [shared], "hr-sub": [shared]}, names={"hr": "HR", "hr-sub": "HR/Policies"})
    scope: dict = {}
    items = scanner._list("drive", svc, folders=["hr", "hr-sub"], scope_out=scope)
    assert len(items) == 1, f"the same file was counted twice: {[i['name'] for i in items]}"
    assert scope["kept"] == 1


def test_the_cap_is_shared_across_roots_not_spent_per_root():
    """Four folders must not quietly list 4x the ceiling while each walk looks correct."""
    tree = {f"f{i}": [_f(f"d{i}a", f"A{i}.docx"), _f(f"d{i}b", f"B{i}.docx")] for i in range(4)}
    svc = _svc(tree)
    scope: dict = {}
    items = scanner._list("drive", svc, folders=list(tree), max_files=3, scope_out=scope)
    assert len(items) <= 3, f"the cap was spent per root: got {len(items)}"
    assert scope["truncated"] is True, "listing stopped early without recording truncation"


# ── the boundary is recorded ─────────────────────────────────────────────────────────────────

def test_the_scope_names_every_chosen_folder():
    """A count needs its boundary, and "3 folders" is not one a reader can check against."""
    svc = _svc({"hr": [_f("d1", "a.docx")], "fin": [_f("d2", "b.docx")]},
               names={"hr": "HR", "fin": "Finance"})
    scope: dict = {}
    scanner._list("drive", svc, folders=["hr", "fin"], scope_out=scope)
    assert [f["name"] for f in scope["folders"]] == ["HR", "Finance"]


def test_kind_stays_folder_for_several_roots():
    """isNarrowScope() keys off `kind`. A new kind here silently drops the ⚠ on a narrowed scan —
    the 2026-07-30 defect, re-introduced by a rename rather than by a logic change."""
    svc = _svc({"hr": [_f("d1", "a.docx")], "fin": [_f("d2", "b.docx")]})
    scope: dict = {}
    scanner._list("drive", svc, folders=["hr", "fin"], scope_out=scope)
    assert scope["kind"] == "folder"


def test_a_single_folder_still_reports_exactly_what_it_did_before():
    """The one-root path is untouched, so an existing scan's scope shape does not move."""
    svc = _svc({"hr": [_f("d1", "a.docx")]}, names={"hr": "HR"})
    scope: dict = {}
    scanner._list("drive", svc, folders=["hr"], scope_out=scope)
    assert scope["kind"] == "folder" and scope["folder_id"] == "hr"
    assert scope["folder_name"] == "HR"


def test_folder_is_still_accepted_so_existing_callers_keep_working():
    svc = _svc({"hr": [_f("d1", "a.docx")]}, names={"hr": "HR"})
    scope: dict = {}
    items = scanner._list("drive", svc, folder="hr", scope_out=scope)
    assert len(items) == 1 and scope["folder_id"] == "hr"


def test_root_is_not_treated_as_a_chosen_folder():
    """"root" is Drive's sentinel for NO narrowing. Treating it as a folder id would turn a
    whole-Drive scan into a subtree walk of a folder literally named "root"."""
    svc = _svc({"hr": [_f("d1", "a.docx")]})
    scope: dict = {}
    scanner._list("drive", svc, folders=["root"], scope_out=scope)
    assert scope["kind"] == "drive", f"'root' narrowed the scan: {scope.get('kind')}"


# ── SharePoint / OneDrive ────────────────────────────────────────────────────────────────────

def test_a_sharepoint_location_carries_its_drive():
    """A Graph item id is unique only WITHIN a drive, so a bare id does not identify a folder.
    _sp_list already stamps driveId per file for this reason; a scope that dropped it would pick
    the signed-in user's folder of that id, or nothing."""
    locs, sites = scanner._sp_locations(["b!drive1/01ITEM"])
    assert locs == [("b!drive1", "01ITEM")]
    assert sites == []


def test_a_bare_id_is_still_read_as_a_site():
    """The site picker has always sent one, so an existing caller must be unchanged."""
    locs, sites = scanner._sp_locations(["contoso.sharepoint.com,guid,guid"])
    assert locs == []
    assert sites == ["contoso.sharepoint.com,guid,guid"]


def test_every_selected_site_is_returned_not_just_the_first():
    """THE multi-site defect, at its source.

    This used to keep the first bare root (`elif site is None`) and drop the rest, silently: a
    request naming three sites was answered with one site's documents, with no error and no
    truncation flag, and every count downstream — coverage, the compliance assertion — was
    computed from a third of the estate the operator asked about.
    """
    locs, sites = scanner._sp_locations(["contoso,a,1", "contoso,b,2", "contoso,c,3"])
    assert locs == []
    assert sites == ["contoso,a,1", "contoso,b,2", "contoso,c,3"]


def test_the_same_site_twice_is_one_site():
    """Not twice the estate — and the duplicate walk would spend budget belonging to a site that
    has not been walked yet."""
    _, sites = scanner._sp_locations(["contoso,a,1", "contoso,a,1"])
    assert sites == ["contoso,a,1"]


def test_sites_and_folders_can_be_mixed():
    locs, sites = scanner._sp_locations(["contoso,a,b", "b!d/01A", "b!d/01B"])
    assert sites == ["contoso,a,b"]
    assert locs == [("b!d", "01A"), ("b!d", "01B")]


def test_a_malformed_location_is_dropped_rather_than_scanning_everything(monkeypatch):
    """A half-written location must not silently widen the scan back to the whole drive."""
    locs, sites = scanner._sp_locations(["b!drive-with-no-item/", "/01ITEM"])
    assert locs == []
    assert sites == []


def test_onedrive_folder_narrowing_is_recorded_as_a_boundary(monkeypatch):
    """THE case the old narrowness test could not see.

    A OneDrive folder scan has kind 'sharepoint' and NO site, so `scope.site` — what
    isNarrowScope() keyed off for this source — is None. Without `folders` on the scope the count
    renders with no boundary and reads as the whole of OneDrive.
    """
    monkeypatch.setattr(scanner, "_sp_list", lambda *a, **k: [], raising=True)
    monkeypatch.setattr(scanner, "_sp_folder_name", lambda t, d, i: "Policies", raising=True)
    scope: dict = {}
    scanner._list("sharepoint", None, folders=["b!d/01A"], sp_token="t", scope_out=scope)
    assert scope["site"] is None
    assert scope["folders"] == [{"id": "b!d/01A", "name": "Policies"}], \
        "a narrowed OneDrive scan recorded no boundary"


def test_a_label_lookup_failure_does_not_fail_the_scan(monkeypatch):
    """Best-effort, like _sp_site_name: this exists so the UI can NAME a boundary, and a scan
    must never die because a label lookup did."""
    monkeypatch.setattr(scanner, "_sp_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("graph down")),
                        raising=True)
    assert scanner._sp_folder_name("tok", "b!d", "01A") is None
