"""Include a parent, carve out a child.

PRD §6.3: a selected parent includes every accessible descendant, and an unchecked child beneath
it becomes an explicit exclusion. "Most specific path wins", and re-inclusion beneath an
exclusion is deliberately not supported in MVP — which is what lets the whole rule be one check
at the point a subfolder would be enqueued.

The cases here exist because THE FAILURE MODE OF EACH IS A NUMBER THAT LOOKS FINE:

  · an exclusion that filters the RESULT instead of pruning the WALK still spends the file cap
    on documents it then discards — so an excluded Archive folder can push wanted files past the
    cap and out of the scan, and the count comes back smaller with nothing to explain it
  · an exclusion applied with no inclusion narrows a whole-estate scan invisibly: no chips on
    the card, no included paths on the review step, just a smaller number
  · an exclusion that is honoured but never RECORDED gives two runs of the same folder two
    different counts with identical boundaries on screen — the 2026-07-30 defect, one level down
  · a descendant of an excluded folder must go too; pruning only the named folder leaves its
    subtree in the scan, which reads as the exclusion having silently failed

Driven against a fake Drive service (the idiom in test_discovery_scope_reported.py) so the real
BFS runs, since the pruning IS in the BFS.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


def _doc(fid, name):
    return {"id": fid, "name": name, "mimeType": DOC}


def _dir(fid, name):
    return {"id": fid, "name": name, "mimeType": FOLDER}


class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self, **kw):
        return self._payload


class FakeFiles:
    def __init__(self, tree, names=None):
        self._tree, self._names = tree, (names or {})
        self.listed_parents = []

    def list(self, **kw):
        q = kw.get("q", "")
        for parent, children in self._tree.items():
            if f"'{parent}' in parents" in q:
                self.listed_parents.append(parent)
                return _Exec({"files": children})
        return _Exec({"files": []})

    def get(self, fileId=None, **kw):
        return _Exec({"name": self._names.get(fileId, fileId)})


class FakeSvc:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


# A programme folder with an Archive branch two levels deep — the shape the PRD's example uses.
TREE = {
    "prog":      [_doc("d1", "Charter.docx"), _dir("arch", "Archive"), _dir("live", "Live")],
    "arch":      [_doc("d2", "Old-2019.docx"), _dir("arch2", "Older")],
    "arch2":     [_doc("d3", "Older-still.docx")],
    "live":      [_doc("d4", "Current.docx")],
}


def _run(exclude=None, roots=("prog",), max_files=1000):
    files = FakeFiles(TREE, names={"prog": "Programme", "arch": "Archive"})
    scope: dict = {}
    items = scanner._list("drive", FakeSvc(files), folders=list(roots),
                          exclude_folders=list(exclude or ()), max_files=max_files,
                          scope_out=scope)
    return items, scope, files


def test_without_exclusions_the_whole_subtree_is_scanned():
    items, _scope, _f = _run()
    assert sorted(i["name"] for i in items) == [
        "Charter.docx", "Current.docx", "Old-2019.docx", "Older-still.docx"]


def test_an_excluded_child_is_carved_out():
    items, _scope, _f = _run(exclude=["arch"])
    assert sorted(i["name"] for i in items) == ["Charter.docx", "Current.docx"]


def test_the_excluded_subtree_goes_too_not_just_the_named_folder():
    """Pruning only the named folder leaves its descendants in the scan, which reads as the
    exclusion having silently failed."""
    items, _scope, _f = _run(exclude=["arch"])
    assert "Older-still.docx" not in [i["name"] for i in items], \
        "a grandchild of the excluded folder survived"


def test_the_excluded_branch_is_never_walked_at_all():
    """Not merely filtered from the result. A post-filter still pages the subtree and spends the
    cap on files it discards — so an excluded Archive can push wanted files past the cap."""
    _items, _scope, f = _run(exclude=["arch"])
    assert "arch" not in f.listed_parents, "the excluded folder was listed anyway"
    assert "arch2" not in f.listed_parents, "the excluded subtree was walked anyway"


def test_the_cap_is_not_spent_on_excluded_files():
    """The consequence of the previous case, stated as the number a user would see.

    With a cap of 2 and Archive excluded, both surviving documents must fit. If the walk spends
    the cap inside Archive first, Current.docx drops out — a scan that lost a file the user
    explicitly kept, with nothing on screen to say why.
    """
    items, _scope, _f = _run(exclude=["arch"], max_files=2)
    assert sorted(i["name"] for i in items) == ["Charter.docx", "Current.docx"]


def test_the_exclusion_is_recorded_on_the_scope():
    """Honoured but unrecorded gives two runs of the same folder two different counts with
    identical boundaries on screen."""
    _items, scope, _f = _run(exclude=["arch"])
    assert scope.get("excluded") == ["arch"]
    assert scope.get("skipped_excluded") == 1


def test_an_exclusion_with_no_inclusion_is_ignored():
    """Nothing to carve out of. Honouring it would narrow a whole-Drive scan with no chips on the
    card and no included paths on the review step — invisible narrowing, the worst kind."""
    files = FakeFiles({"root": [_doc("d9", "Loose.docx")]})
    scope: dict = {}
    scanner._list("drive", FakeSvc(files), folder=None, exclude_folders=["arch"], scope_out=scope)
    assert scope["kind"] == "drive", "an exclusion alone narrowed the scan"
    assert "excluded" not in scope


def test_exclusions_apply_across_several_included_roots():
    tree = dict(TREE, other=[_doc("d5", "Other.docx"), _dir("arch", "Archive")])
    files = FakeFiles(tree, names={"prog": "Programme", "other": "Other"})
    scope: dict = {}
    items = scanner._list("drive", FakeSvc(files), folders=["prog", "other"],
                          exclude_folders=["arch"], scope_out=scope)
    assert "Old-2019.docx" not in [i["name"] for i in items]
    assert "Other.docx" in [i["name"] for i in items]


def test_a_single_root_with_no_exclusions_is_byte_identical_to_before():
    """The pre-existing one-folder path must not move — its scope shape is what the UI reads."""
    _items, scope, _f = _run()
    assert scope["kind"] == "folder" and scope["folder_id"] == "prog"
    assert scope["folder_name"] == "Programme"
    assert "excluded" not in scope
