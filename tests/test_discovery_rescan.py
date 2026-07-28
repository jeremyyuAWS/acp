"""Discovery must re-list Drive on every scan, so files added since the last scan are found.

The worry this pins down: a user adds files to Drive, re-runs a scan, and the new files are
missing because something served a cached inventory. ACP DOES cache — `store.find_prior_analysis`
reuses a file's analysis across scans — and it would be easy to assume that caching extends to
discovery. It must not, and these tests are the guarantee rather than an assurance:

  * discovery holds no memo. Two scans issue two independent `files.list` calls.
  * a file that appears between scans is discovered by the second one.
  * analysis reuse is keyed on a file's own identity + content, so it can never suppress a file
    that was not in the earlier scan at all.

If someone later adds an lru_cache to `_search_drive`/`_search_folder` for speed, or memoises the
Drive service's results, these go red — which is the point. The expensive thing is per-file
ANALYSIS, and that is already cached at the right layer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import scanner  # noqa: E402

DOC_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _FakeList:
    """One `files().list(...)` call — records it, returns the current page set."""

    def __init__(self, svc, kwargs):
        self._svc, self._kwargs = svc, kwargs

    def execute(self, **_):
        self._svc.calls.append(self._kwargs)
        # Folder-probe calls ask only for ids; the BFS uses them to walk subtrees. No subfolders
        # in these fixtures, so an empty list ends the walk immediately.
        if self._kwargs.get("fields") == "files(id)":
            return {"files": []}
        if "mimeType='application/vnd.google-apps.folder'" in (self._kwargs.get("q") or ""):
            return {"files": []}
        return {"files": list(self._svc.files_now), "nextPageToken": None}


class _FakeFiles:
    def __init__(self, svc):
        self._svc = svc

    def list(self, **kwargs):
        return _FakeList(self._svc, kwargs)


class FakeDrive:
    """A Drive whose contents can change between scans, like a real one."""

    def __init__(self, files):
        self.files_now = files
        self.calls: list[dict] = []

    def files(self):
        return _FakeFiles(self)


def _file(fid: str, name: str) -> dict:
    return {"id": fid, "name": name, "mimeType": DOC_MIME,
            "modifiedTime": "2026-07-28T00:00:00Z", "size": "1024"}


def test_a_second_scan_lists_drive_again_rather_than_reusing_the_first():
    """No memoisation: two scans, two real listings."""
    drive = FakeDrive([_file("a", "one.docx")])
    scanner._search_folder(drive, "folder-1")
    after_first = len(drive.calls)
    assert after_first >= 1, "discovery issued no Drive call at all"

    scanner._search_folder(drive, "folder-1")
    assert len(drive.calls) > after_first, (
        "the second scan issued no new files.list call — discovery is serving a cached "
        "inventory, so files added since the first scan can never be found")


def test_a_file_added_between_scans_is_discovered():
    """The user's actual scenario: upload, re-scan, expect to see it."""
    drive = FakeDrive([_file("a", "one.docx")])
    first = scanner._search_folder(drive, "folder-1")
    assert [f["name"] for f in first] == ["one.docx"]

    drive.files_now.append(_file("b", "two.docx"))          # uploaded between scans
    second = scanner._search_folder(drive, "folder-1")
    assert sorted(f["name"] for f in second) == ["one.docx", "two.docx"], (
        "a file added between scans was not discovered by the rescan")


def test_whole_drive_search_also_re_lists():
    """Same guarantee on the un-foldered path, which uses a different query builder."""
    drive = FakeDrive([_file("a", "one.docx")])
    scanner._search_drive(drive)
    after_first = len(drive.calls)
    drive.files_now.append(_file("b", "two.docx"))
    names = [f["name"] for f in scanner._search_drive(drive)]
    assert len(drive.calls) > after_first
    assert "two.docx" in names


def test_newest_files_are_listed_first_so_the_cap_cannot_hide_a_new_upload():
    """The cap is the one way a new file could still be missed on a very large Drive.

    `orderBy="modifiedTime desc"` is what makes that safe: when the raw cap bites, the files
    dropped are the OLDEST, never the just-uploaded ones. This asserts the ordering is actually
    requested — a silent change to it would reintroduce exactly the reported symptom, on
    precisely the estates too big to notice it on.
    """
    drive = FakeDrive([_file("a", "one.docx")])
    scanner._search_folder(drive, "folder-1")
    scanner._search_drive(drive)
    listings = [c for c in drive.calls if c.get("fields", "").startswith("nextPageToken")]
    assert listings, "no paginated listing call was made"
    for call in listings:
        assert call.get("orderBy") == "modifiedTime desc", (
            f"listing without newest-first ordering: {call.get('q')!r} — a capped scan would "
            f"drop the most recently uploaded files instead of the oldest")


def test_discovery_module_holds_no_result_cache():
    """A structural guard: nothing in the discovery path is memoised.

    Cheaper and broader than the behavioural tests above — it catches a cache added to a helper
    they don't happen to cover.
    """
    import inspect
    src = inspect.getsource(scanner)
    for marker in ("@lru_cache", "@functools.lru_cache", "@cache", "@functools.cache"):
        assert marker not in src, (
            f"{marker} appears in scanner.py — if it decorates any part of discovery, a rescan "
            f"will not see newly added files. Cache per-file ANALYSIS "
            f"(store.find_prior_analysis), never the inventory.")


def test_analysis_reuse_cannot_suppress_an_unseen_file():
    """The legitimate cache, bounded correctly.

    `find_prior_analysis` is gated on owner + drive_file_id + checksum + rubric_hash. A file that
    was not in the previous scan has no prior row to match, so reuse returns None and it gets a
    real analysis. Any of the four missing short-circuits — this asserts that guard directly,
    since it is what keeps a per-file cache from behaving like an inventory cache.
    """
    import store
    st = store.Store.__new__(store.Store)          # no DB needed: the guard returns before any query
    for args in (
        (None, "drive-id", "sum", "rubric"),       # no owner
        ("me@example.com", None, "sum", "rubric"),  # never seen before -> no drive_file_id
        ("me@example.com", "drive-id", None, "rubric"),
        ("me@example.com", "drive-id", "sum", None),
    ):
        assert store.Store.find_prior_analysis(st, *args) is None
