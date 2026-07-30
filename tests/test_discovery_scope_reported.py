"""Discovery states WHAT it covered, not only how many files it found.

The incident this pins, from production logs on 2026-07-30, one account, six seconds apart:

    01:38:35  POST /scans?source=drive&folder=1W27ULZ…  →  folder subtree: 1 listed · 1 scannable
    01:38:41  POST /scans?source=drive                 →  whole-Drive: 11 raw · 8 scannable · 8 kept

Reported as "a scan discovers only 1 file when there are 8". Both listings were correct — the
folder held one document, the Drive held eight — and the six-second gap is what rules out every
credential explanation, since one token cannot be simultaneously too narrow to list eight files
and wide enough to list eight files. The defect was that a scan recorded no boundary, so the UI
could only ever print the count, and 1-then-8 read as an estate losing seven documents.

These tests are written against fake Drive services rather than mocks of our own functions, so
they exercise the real paging/BFS/normalise path that produced those two numbers.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402


DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


def _f(fid, name, mime=DOC, **extra):
    return {"id": fid, "name": name, "mimeType": mime, **extra}


class FakeFiles:
    """Drive files() double. `pages` maps a query substring → list of response pages."""

    def __init__(self, pages, names=None):
        self._pages = pages
        self._names = names or {}
        self.list_calls = []
        self.get_calls = []

    def list(self, **kw):
        self.list_calls.append(kw)
        q = kw.get("q", "")
        token = kw.get("pageToken")
        for key, pages in self._pages.items():
            if key in q:
                idx = 0 if token is None else int(token)
                page = pages[idx] if idx < len(pages) else {"files": []}
                return _Exec(page)
        return _Exec({"files": []})

    def get(self, fileId=None, **kw):
        self.get_calls.append(fileId)
        if fileId in self._names:
            return _Exec({"name": self._names[fileId]})
        raise RuntimeError("no such file")


class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self, **kw):
        return self._payload


class FakeSvc:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


# ── The two production listings, reproduced ────────────────────────────────────────────────

def test_folder_scan_of_a_one_file_folder_reports_the_folder_as_its_boundary():
    """The 01:38:35 scan. One document is the RIGHT answer; the scope is what was missing."""
    svc = FakeSvc(FakeFiles(
        {"'1W27ULZ' in parents": [{"files": [_f("d1", "Defense-Pack-README.docx")]}]},
        names={"1W27ULZ": "WCAG Defense Pack"},
    ))
    scope: dict = {}
    items = scanner._list("drive", svc, folder="1W27ULZ", scope_out=scope)

    assert len(items) == 1                      # the count production reported
    assert scope["kind"] == "folder"
    assert scope["folder_id"] == "1W27ULZ"
    assert scope["folder_name"] == "WCAG Defense Pack"
    assert scope["kept"] == 1
    # A folder listing that covered its whole folder is NOT truncated. Conflating "small" with
    # "incomplete" would put "we could not see everything" on a scan that saw everything asked of
    # it — the opposite error, and just as misleading.
    assert scope["truncated"] is False


def test_whole_drive_scan_reports_the_drive_as_its_boundary():
    """The 01:38:41 scan: 11 raw items, 8 of them scannable."""
    raw = [_f(f"d{i}", f"Brief-{i}.docx") for i in range(8)]
    raw += [_f(f"x{i}", f"image-{i}.png", mime="image/png") for i in range(3)]
    svc = FakeSvc(FakeFiles({"trashed=false": [{"files": raw}]}))
    scope: dict = {}
    items = scanner._list("drive", svc, folder=None, scope_out=scope)

    assert len(items) == 8
    assert scope["kind"] == "drive"
    assert scope["raw"] == 11
    assert scope["scannable"] == 8
    assert scope["kept"] == 8
    assert scope["truncated"] is False


def test_the_two_scopes_are_distinguishable_from_the_scan_record_alone():
    """The actual regression guard: 1 and 8 must not be two readings of the same measurement.

    Without a recorded scope both scans are `source='drive'` with a file count, which is exactly
    what the scan-history table rendered in adjacent rows.
    """
    folder_svc = FakeSvc(FakeFiles({"'F' in parents": [{"files": [_f("d1", "a.docx")]}]},
                                   names={"F": "Defense Pack"}))
    drive_svc = FakeSvc(FakeFiles(
        {"trashed=false": [{"files": [_f(f"d{i}", f"b{i}.docx") for i in range(8)]}]}))

    narrow, wide = {}, {}
    scanner._list("drive", folder_svc, folder="F", scope_out=narrow)
    scanner._list("drive", drive_svc, folder=None, scope_out=wide)

    assert narrow["kind"] != wide["kind"]
    assert narrow["kind"] == "folder" and wide["kind"] == "drive"


# ── Truncation: the case where "we could not see the rest" is literally true ───────────────

def test_a_capped_folder_listing_says_it_did_not_list_everything():
    pages = [{"files": [_f(f"d{i}", f"f{i}.docx") for i in range(200)], "nextPageToken": "1"},
             {"files": [_f(f"e{i}", f"g{i}.docx") for i in range(200)]}]
    svc = FakeSvc(FakeFiles({"'F' in parents": pages}, names={"F": "Big"}))
    scope: dict = {}
    items = scanner._list("drive", svc, folder="F", max_files=200, scope_out=scope)

    assert len(items) == 200
    assert scope["truncated"] is True
    assert scope["cap"] == 200


def test_a_capped_whole_drive_listing_says_it_did_not_list_everything():
    """max_files below the scannable count truncates even when the raw cap was never reached."""
    raw = [_f(f"d{i}", f"f{i}.docx") for i in range(10)]
    svc = FakeSvc(FakeFiles({"trashed=false": [{"files": raw}]}))
    scope: dict = {}
    items = scanner._list("drive", svc, folder=None, max_files=4, scope_out=scope)

    assert len(items) == 4
    assert scope["truncated"] is True


# ── Boundary conditions ───────────────────────────────────────────────────────────────────

def test_kept_counts_rows_the_ui_will_show_not_rows_drive_returned():
    """Two DIFFERENT files sharing a name become two rows, and `kept` must match the rows.

    _dedupe_names runs after the search functions set `kept`, so the number stated beside the
    scope has to be re-read afterwards or it can disagree with the list on screen.
    """
    svc = FakeSvc(FakeFiles(
        {"'F' in parents": [{"files": [_f("d1", "Report.docx"), _f("d2", "Report.docx")]}]},
        names={"F": "Dupes"}))
    scope: dict = {}
    items = scanner._list("drive", svc, folder="F", scope_out=scope)
    assert scope["kept"] == len(items) == 2


def test_an_empty_folder_still_records_its_scope():
    """Zero documents is when "what did this look at?" matters most."""
    svc = FakeSvc(FakeFiles({"'F' in parents": [{"files": []}]}, names={"F": "Empty"}))
    scope: dict = {}
    assert scanner._list("drive", svc, folder="F", scope_out=scope) == []
    assert scope["kind"] == "folder"
    assert scope["folder_name"] == "Empty"
    assert scope["kept"] == 0


def test_a_folder_name_lookup_failure_never_fails_the_scan():
    """The label is a nicety; the listing is the product. An unnameable folder still scans."""
    svc = FakeSvc(FakeFiles({"'GONE' in parents": [{"files": [_f("d1", "a.docx")]}]}, names={}))
    scope: dict = {}
    items = scanner._list("drive", svc, folder="GONE", scope_out=scope)
    assert len(items) == 1
    assert scope["kind"] == "folder"
    assert scope["folder_name"] is None       # unknown, not invented


def test_scope_out_is_optional_so_existing_callers_are_unaffected():
    svc = FakeSvc(FakeFiles({"'F' in parents": [{"files": [_f("d1", "a.docx")]}]}, names={"F": "X"}))
    assert len(scanner._list("drive", svc, folder="F")) == 1
    # …and no folder-name lookup is spent when nobody asked for the label.
    assert svc.files().get_calls == []


def test_local_and_sharepoint_scopes_are_named_too(tmp_path, monkeypatch):
    (tmp_path / "a.docx").write_bytes(b"x")
    monkeypatch.setenv("ACP_LOCAL_CORPUS", str(tmp_path))
    scope: dict = {}
    items = scanner._list("local", scope_out=scope)
    assert len(items) == 1
    assert scope["kind"] == "local"
    assert scope["truncated"] is False

    monkeypatch.setattr(scanner, "_sp_list", lambda tok, n: [{"name": "a.docx", "id": "1"}])
    sp: dict = {}
    scanner._list("sharepoint", sp_token="t", scope_out=sp)
    assert sp["kind"] == "sharepoint"


def test_subfolder_count_is_recorded_so_the_ui_can_say_what_was_walked():
    pages = {
        "'ROOT' in parents": [{"files": [_f("SUB", "Sub", mime=FOLDER), _f("d1", "a.docx")]}],
        "'SUB' in parents": [{"files": [_f("d2", "b.docx")]}],
    }
    svc = FakeSvc(FakeFiles(pages, names={"ROOT": "Estate"}))
    scope: dict = {}
    items = scanner._list("drive", svc, folder="ROOT", scope_out=scope)
    assert len(items) == 2
    assert scope["folders_walked"] == 2
    assert scope["listed"] == 2
