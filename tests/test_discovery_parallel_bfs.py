"""Parallel BFS in _search_folder: multi-level trees are fully traversed.

The serial BFS processed one folder per iteration; the parallel version submits
up to _DISCOVERY_WORKERS folders simultaneously and enqueues their children as
results arrive.  These tests pin the observable contract — correct files from
deep and wide trees — which must hold regardless of scheduling order.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


class _Req:
    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _Files:
    def __init__(self, drive):
        self.d = drive

    def list(self, **kw):
        q = kw.get("q", "")
        fid = q.split("'")[1] if q.startswith("'") else None
        files = self.d.children.get(fid, []) if fid else []
        return _Req({"files": files})


class FakeDrive:
    def __init__(self, children):
        self.children = children  # {folder_id: [file/folder dicts]}

    def files(self):
        return _Files(self)


def _doc(fid, name="doc.docx"):
    return {"id": fid, "name": name, "mimeType": DOCX}


def _folder(fid, name="subfolder"):
    return {"id": fid, "name": name, "mimeType": FOLDER}


def test_two_level_tree_all_files_found():
    """root → [A, B] → each has one file; both files must be returned."""
    drive = FakeDrive({
        "root": [_folder("A"), _folder("B")],
        "A":    [_doc("f1", "alpha.docx")],
        "B":    [_doc("f2", "beta.docx")],
    })
    result = scanner._search_folder(drive, "root", max_files=100)
    ids = {r["id"] for r in result}
    assert ids == {"f1", "f2"}


def test_three_level_tree_deeply_nested_file_found():
    """root → A → B → file; three hops deep must still be reached."""
    drive = FakeDrive({
        "root": [_folder("A")],
        "A":    [_folder("B")],
        "B":    [_doc("deep", "buried.docx")],
    })
    result = scanner._search_folder(drive, "root", max_files=100)
    assert len(result) == 1
    assert result[0]["id"] == "deep"


def test_wide_tree_all_subfolders_walked():
    """root with 10 subfolders, one file each — all 10 files returned."""
    children = {"root": [_folder(f"F{i}") for i in range(10)]}
    for i in range(10):
        children[f"F{i}"] = [_doc(f"file{i}", f"doc{i}.docx")]
    drive = FakeDrive(children)
    result = scanner._search_folder(drive, "root", max_files=500)
    assert len(result) == 10
    assert {r["id"] for r in result} == {f"file{i}" for i in range(10)}


def test_cycle_guard_prevents_infinite_loop():
    """A folder that references itself (or its ancestor) must not cause an infinite loop."""
    drive = FakeDrive({
        "root": [_folder("A")],
        "A":    [_folder("root"), _doc("f1")],  # root seen again — must be skipped
    })
    result = scanner._search_folder(drive, "root", max_files=100)
    assert len(result) == 1
    assert result[0]["id"] == "f1"


def test_scope_out_folders_walked_counts_all_visited():
    """scope_out.folders_walked reflects the total number of unique folders entered."""
    drive = FakeDrive({
        "root": [_folder("A"), _folder("B")],
        "A":    [_doc("f1")],
        "B":    [_doc("f2")],
    })
    scope: dict = {}
    scanner._search_folder(drive, "root", max_files=100, scope_out=scope)
    # root + A + B = 3 folders walked
    assert scope["folders_walked"] == 3
    assert scope["kept"] == 2
