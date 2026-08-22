"""A folder-scoped Drive discovery must write `scope.inventory`, the same as a whole-Drive one.

Found live 2026-08-21, minutes after #624 shipped: a real 170-file account, scoped to
"Specific folders" (the common real-world choice, not "Entire Drive"), still showed
"0 documents will be opened and scored" on Assess. #624 fixed the DISCOVER-ONLY-SCAN-IS-
INVISIBLE half of that bug; this is the other half. `/assess/eligibility` reads
`scan_runs.scope.inventory` — the `estate_inventory.summarize()` snapshot a discovery run
persists — but `_search_folder`/`_search_folders` in api/scanner.py never wrote it, unlike
`_search_drive` (whole-Drive) and `_sp_list` (SharePoint). A folder-scoped scan produced a
real per-file `scan_inventory` (so Discover's own screen looked correct) while leaving
`scope["inventory"]` entirely absent — so anything reading that field, not just eligibility,
saw nothing for any folder-scoped Drive account regardless of estate size.

Driven against a fake Drive service (the idiom in test_folder_exclusions.py) so the real BFS
paths run — both `_search_folder` (single root, `_list`'s own branch) and `_search_folders`
(several roots, unioned)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import estate_inventory  # noqa: E402
import scanner  # noqa: E402

DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF = "application/pdf"
FOLDER = "application/vnd.google-apps.folder"


def _doc(fid, name, mime=DOC):
    return {"id": fid, "name": name, "mimeType": mime}


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

    def list(self, **kw):
        q = kw.get("q", "")
        for parent, children in self._tree.items():
            if f"'{parent}' in parents" in q:
                return _Exec({"files": children})
        return _Exec({"files": []})

    def get(self, fileId=None, **kw):
        return _Exec({"name": self._names.get(fileId, fileId)})


class FakeSvc:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


# Two independent branches — HR and Finance — the "several chosen folders" shape.
TREE = {
    "hr":      [_doc("d1", "Handbook.docx"), _doc("d2", "Scan.pdf", mime=PDF)],
    "finance": [_doc("d3", "Budget.docx")],
}


def test_a_single_chosen_folder_gets_a_real_inventory_summary():
    """_list's single-root branch (`_search_folder` directly) — the byte-identical-scope path
    the dispatch comment guards. Before the fix, scope.get("inventory") was simply absent."""
    scope: dict = {}
    items = scanner._list("drive", FakeSvc(FakeFiles(TREE)), folders=["hr"], scope_out=scope)
    assert len(items) == 2
    inv = scope.get("inventory")
    assert isinstance(inv, dict), "scope['inventory'] was never written for a folder-scoped scan"
    assert inv["discovered"] == 2
    assert inv["assessment_eligible"] == 2
    assert inv["by_format"].get("docx") == 1
    assert inv["by_format"].get("pdf") == 1


def test_several_chosen_folders_get_one_combined_inventory_not_none():
    """_search_folders' union branch — the multi-folder scope our live test account actually
    used (3 Drive folders). Regression: this previously had no 'inventory' key at all, so
    /assess/eligibility's _latest_inventory found nothing for this scan regardless of how many
    other scans this owner had."""
    scope: dict = {}
    items = scanner._list("drive", FakeSvc(FakeFiles(TREE)), folders=["hr", "finance"],
                          scope_out=scope)
    assert len(items) == 3
    inv = scope.get("inventory")
    assert isinstance(inv, dict), "scope['inventory'] was never written for a multi-folder scan"
    assert inv["discovered"] == 3
    assert inv["assessment_eligible"] == 3
    assert inv["by_format"] == {"docx": 2, "pdf": 1}


def test_the_combined_inventory_matches_summarizing_the_union_directly():
    """Not just non-empty — the SAME numbers a direct summarize() over the raw union would give,
    so the fix isn't just plausible-looking zeros replaced with plausible-looking wrong numbers."""
    scope: dict = {}
    scanner._list("drive", FakeSvc(FakeFiles(TREE)), folders=["hr", "finance"], scope_out=scope)
    expected = estate_inventory.summarize(
        [_doc("d1", "Handbook.docx"), _doc("d2", "Scan.pdf", mime=PDF), _doc("d3", "Budget.docx")])
    assert scope["inventory"]["discovered"] == expected["discovered"]
    assert scope["inventory"]["by_format"] == expected["by_format"]
